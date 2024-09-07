import requests

def get_top_50_lp_holders():
    url = "https://gql.ergoplatform.com/"
    limit = 50
    offset = 0
    all_lp_holders = []
    has_more = True

    query_dex_box = """
    query {
        boxes(tokenId: "1b694b15467c62f0cd4525e368dbdea2329c713aa200b73df4a622e950551b40", spent: false) {
            value
            assets {
                tokenId
                amount
            }
        }
    }
    """

    # Fetch the dex box to get the LP token ID
    response = requests.post(url, json={'query': query_dex_box})
    dex_box_data = response.json()

    if 'data' in dex_box_data and dex_box_data['data']['boxes']:
        dex_box = dex_box_data['data']['boxes'][0]
        lp_token_id = dex_box['assets'][1]['tokenId']  # LP token ID
    else:
        return "Failed to fetch the DEX box or no DEX box found."

    print(f"LP Token ID: {lp_token_id}")

    # Loop to handle pagination and collect all LP holders
    while has_more:
        query_lp_holders = f"""
        query {{
            boxes(tokenId: "{lp_token_id}", spent: false, take: {limit}, skip: {offset}) {{
                address
                boxId
                assets {{
                    tokenId
                    amount
                }}
            }}
        }}
        """

        response = requests.post(url, json={'query': query_lp_holders})
        lp_holders_data = response.json()

        if 'data' in lp_holders_data and lp_holders_data['data']['boxes']:
            lp_boxes = lp_holders_data['data']['boxes']
            all_lp_holders.extend(lp_boxes)

            # If fewer results than the limit, we've reached the last page
            if len(lp_boxes) < limit:
                has_more = False
            else:
                offset += limit
        else:
            has_more = False

    # Sort holders by the amount of LP tokens they hold in descending order
    def find_lp_amount(box):
        # Find the asset that matches the LP token ID
        for asset in box['assets']:
            if asset['tokenId'] == lp_token_id:
                return int(asset['amount'])
        return 0

    # Sort holders by the amount of LP tokens they hold
    sorted_lp_holders = sorted(all_lp_holders, key=find_lp_amount, reverse=True)

    # Get the top 50 holders
    top_50_lp_holders = sorted_lp_holders[1:51]
    print(top_50_lp_holders)

    max_lp = 9223372036854775807
    lp_circulation = max_lp - find_lp_amount(sorted_lp_holders[0])
    print(lp_circulation)

    # Sum the total amount of LP tokens held by the top 50 holders
    total_lp_tokens = sum(find_lp_amount(holder) for holder in top_50_lp_holders)


    return total_lp_tokens, top_50_lp_holders


# Call the function and display results
total_lp_tokens_held, top_50_holders = get_top_50_lp_holders()
print(f"Total LP tokens held by top 50 holders: {total_lp_tokens_held}")
