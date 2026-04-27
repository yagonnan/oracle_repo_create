# poll_oracle.py
import oci
import os
import requests
import json
from base64 import b64decode

def get_oci_config():
    """
    Build OCI config from environment variables injected by GitHub Actions.
    We write the private key to a temp file because the OCI SDK expects a file path.
    """
    key_content = os.environ["OCI_PRIVATE_KEY"]
    
    # Write the private key to a temporary file
    key_path = "/tmp/oci_key.pem"
    with open(key_path, "w") as f:
        f.write(key_content.replace("\\n", "\n"))  # Handle newlines from GitHub Secrets
    
    return {
        "user": os.environ["OCI_USER_OCID"],
        "fingerprint": os.environ["OCI_FINGERPRINT"],
        "tenancy": os.environ["OCI_TENANCY_OCID"],
        "region": os.environ["OCI_REGION"],
        "key_file": key_path
    }

def send_telegram_notification(message):
    """
    Send a Telegram message when instance is created (or when an error occurs).
    This is crucial — you won't be watching the logs, so you need a push notification.
    """
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": message})

def try_create_instance(config):
    """
    Attempt to create the Oracle ARM instance.
    Returns True if successful, False if capacity is unavailable.
    """
    compute_client = oci.core.ComputeClient(config)
    
    # These values come from your Oracle console — replace with your actual OCIDs
    COMPARTMENT_ID = os.environ["OCI_TENANCY_OCID"]  # Root compartment = tenancy
    SUBNET_ID = os.environ.get("OCI_SUBNET_ID", "")
    IMAGE_ID = os.environ.get("OCI_IMAGE_ID", "")     # Ubuntu 22.04 ARM image OCID
    
    instance_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=COMPARTMENT_ID,
        display_name="free-tier-vm",
        
        # ARM Ampere shape — this is the powerful free tier option (4 OCPU, 24GB RAM)
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=4,          # Max free tier: 4 OCPUs total across all ARM instances
            memory_in_gbs=24  # Max free tier: 24GB RAM total
        ),
        
        availability_domain=os.environ["OCI_AVAILABILITY_DOMAIN"],  # Get from OCI console
        subnet_id=SUBNET_ID,
        
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=IMAGE_ID,
            source_type="image"
        ),
        
        # Inject your SSH public key so you can log in after creation
        metadata={
            "ssh_authorized_keys": os.environ.get("SSH_PUBLIC_KEY", "")
        }
    )
    
    try:
        response = compute_client.launch_instance(instance_details)
        return True, response.data
    
    except oci.exceptions.ServiceError as e:
        # Error code 500 with "Out of capacity" is the specific message Oracle returns
        if "Out of host capacity" in str(e.message):
            print(f"No capacity available. Will retry next run.")
            return False, None
        else:
            # Something else went wrong (auth error, wrong OCID, etc.) — notify immediately
            send_telegram_notification(f"Oracle poller error (not capacity): {e.message}")
            raise

def main():
    config = get_oci_config()
    
    success, instance_data = try_create_instance(config)
    
    if success:
        # This is the moment you've been waiting for — send a Telegram alert immediately
        message = (
            f"✅ Oracle Free Tier instance CREATED!\n"
            f"Instance ID: {instance_data.id}\n"
            f"State: {instance_data.lifecycle_state}\n"
            f"Go to your OCI console NOW to confirm."
        )
        send_telegram_notification(message)
        print("SUCCESS:", message)
    else:
        # Normal outcome — just log it, no notification needed
        print("No capacity this run. GitHub Actions will retry in 5 minutes.")

if __name__ == "__main__":
    main()
