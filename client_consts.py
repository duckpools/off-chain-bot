import os

# Set Constants Here
#node_url = "http://159.65.250.130:9053"
node_url = "http://104.131.9.252:9053"
explorer_url = "https://api.ergoplatform.com/api/v1"
headers = {
    "api_key": os.environ["API_KEY"]
}
node_pass = os.environ["WALLET_PASS"]
node_address = "9gf5qJKw3wD99NbsjnXD32Wek8LPbVMn2rxWp39ftiPLDkcKJu4"
AUTOMATIC_PROCESSING_ENABLED = True
