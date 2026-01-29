import os

def format_frontend_output(pool: dict):
    """
    Generates a newPool.ts file with the pool configuration for frontend use.

    Args:
        pool: Dictionary containing pool data from the bootstrapping process.
              Required keys: pool, collateral, repayment, interest, proxy_borrow,
                            POOL_NFT, INTEREST_NFT, PARAMETER_NFT, INTEREST_PARAMETER_NFT,
                            LEND_TOKEN, BORROW_TOKEN
    """

    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(output_dir, "newPool.ts")

    ts_content = f'''  'poolScript': '{pool["pool"]}',
  'collateralScript':
  '{pool["collateral"]}',
  'repaymentScript': '{pool["repayment"]}',
  'interestScript': '{pool["interest"]}',

  proxyLendScript: "KeFZdXyRkmbbDumvWSR1sijFcEbnqF7EL3YprErvspPHs3wmQ3qcD64X5JdjYARbxF4SAYivys3FgqfDgdjQNoa5ULahXEY4SAQNPPK6VLZFMGHjBmzgo7CS5MTDxcuxLvrFUZVHthy2y5DK7Bf7TqUC5TQoVFQxEgsLNpHSd5eG7s9KoGdVY2H1s4HhiEgAzUTmTqiQSaeUr4qpn8erxg8ajR74W4bVyBzovJ8oduDiHPznnrCZnZBhU3NdjLre3MDBHqEkrHnpR9hkEgACDxDLaS8cvaLXsRdejY9qaohVs",
  proxyWithdrawScript: "3rEnDaoVvvfRygpGSe76qKfAi1AHLHH8xH28rWysgHDT1TwUEcY87z8NhN7TPjshdUXCXmSxfqH3U9VTH7PoSnfVp9J9CCKKUWWtb4SQbz4SetmN7qk2JNNrMoBUfaqY2YwyVJyvjx3hszibW8wJhc8eCECpCRGUTTmrjFRvQHUYRhP47DBAVWPVgkQeMDU46rw6jYBR2aooRtyjHZKsbc8WAoNjPpdmNYjv9JtJmrMNDnsX7rWqmWWsGuv953SipQsAsAZhxezGLHGEuPKKAFruJn1Pbus2N6qT3ZkP",
  proxyBorrowScript:
  "{pool["proxy_borrow"]}",
  proxyPartialRepayScript: "25kk6dLZPWxTyL6orVYpVJPHRiv1am3wmo7a9qw6WPPWgur7qPnZCLWxGngiu9zpikPwppzGoSN7MaZNDAtvxLxg4BnQNR7x2JihrXJFj8JeQxmNK7G9VkQ5hyAivjemLTrdhmJNx7hJyMC2zcYNJqBn3wgJ3T4wpHTvAvYD9cNN7eUdGXW3EkGrcVgH9q9Dkxg9s8dk5jmdoMfoKzQX6FKXfwHHSgEyNt6Nd76gzbdHpwYAtStnZbk4zuqra8FttQ",
  proxyRepayScript: "TwyqbJtQAJCTiZsGAy9R1Uc2gwBWn66uNGyzAEMYtpYmRjm4DKFZcrkyQyNAao4U7E3tgoQ87RvECZm1vuGeTLFZvu98ThquQEBE2eR8C7SCGY4jKFt39hSZE3io2UL7FCadtMbAru3kNbmihaJEXsQtsYaSFzgPpNa5NLkr9Znxp79oji",
  // Pool-specific values
  pooledAsset: supportedAssets.quacks,

  poolNFT: "{pool["POOL_NFT"]}",
  lendTokenId: "{pool["LEND_TOKEN"]}",
  borrowTokenId: "{pool["BORROW_TOKEN"]}",
  interestNFT: "{pool["INTEREST_NFT"]}",
  settingsNFT: "{pool["PARAMETER_NFT"]}",
  interestParameterNFT: "{pool["INTEREST_PARAMETER_NFT"]}",'''

    with open(output_path, 'w') as f:
        f.write(ts_content)

    print(f"Frontend output written to: {output_path}")
