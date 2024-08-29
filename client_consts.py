import os
explorer_url = "https://api.ergoplatform.com/api/v1"

# Set Constants Here
node_url = "http://158.64.250.130:9053"
headers = {
    "api_key": os.environ["API_KEY"]
}
node_pass = os.environ["WALLET_PASS"]
node_address = "9i9RhfdHQA2bHA8GqWKkYevp3nozASRjJfFkh29utjNL9gqE7Q7"

# Liquidation Settings
setup_on = False
add_liquidation_boxes_on = False

# Arbitrage Settings
arbitrage_on = False
arbitrage_address = ""
