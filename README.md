# duckpools off-chain bots

## Overview
Orders placed via the duckpools.io user interface (UI) undergo off-chain processing to enhance efficiency and scalability. Off-chain bots — automated programs that operate outside of the blockchain — scan for these pending orders and queue them for submission to the blockchain. This mechanism allows for increased concurrent usage of the protocol.

## Key Features
* **Open Participation:** This system of processing is designed so that anyone can operate an off-chain bot, thereby fostering decentralized order handling.
* **Fee Mechanism**: Off-chain bots can earn a small fee from many of the transactions they handle. Specifically, the protocol ensures rewards for processing interest updates and liquidations. Some orders made via the user interface also include a nominal fee per completed transaction.

## Requirements

To operate the off-chain bot, you'll need to fulfil the following prerequisites:

### Ergo-Node Setup
- You must have an Ergo-Node properly configured and running.
- The node should have a wallet set up with a minimum balance of 0.1 ERG to handle transaction fees and other operations.

### Hardware
- The bot has minimal computational needs; there are no explicit prerequisites for hardware.

### Software
- Python 3.x must be installed on the machine where you plan to run the off-chain bot.
- Python requests module installed.

Please ensure all the above requirements are met before proceeding with the setup steps.

## Steps to Run the Off-Chain Bot

### Step 1: Configure Constants

1. Open the file `client_consts.py` in a text editor of your choice.
2. Locate and fill in the following parameters:
    - `node_url`: The URL of your node.
    - `explorer_url`: The explorer API URL you wish to use.
    - `api_key`: Your node's API key.
    - `node_pass`: Your node's wallet password.
    - `node_address`: Your node's wallet address.
### Step 2: Execute `setup.py`

1. Open your terminal and navigate to the folder where `setup.py` is located.
2. Run the following command:
    ```bash
    python3 setup.py
    ```
    **Note**: Running this setup file will spend 0.074 ERG to create boxes that are spendable only by your node. These boxes are necessary for executing liquidation transactions. If you choose to stop running the off-chain bot in the future, you can collect these boxes.

### Step 3: Run `main.py`

1. Once the setup is complete, run `main.py` using the following command:
    ```bash
    python3 main.py
    ```

Your off-chain bot should now be up and running. If you encounter any issues, please feel free to contact duckpools community Discord.

## Updating the Off-Chain Bot

To update the Off-Chain Bot, generally you will simply need to:

1. Stop the `main.py` script if it is currently running.
2. Use git stash to save your constants in the `client_consts.py` file.
     ```bash
    git stash
    ```
4. Pull the latest changes from the remote repository using:
      ```bash
    git pull
    ```
6. Re-apply your local changes using:
     ```bash
    git stash apply
    ```

## How to Terminate the Off-Chain Bot

If you decide to stop running the off-chain bot indefinitely, follow the steps below to properly terminate it and collect your setup UTXOs. Keep in mind that reactivating the bot will require you to go through the setup process again.

### Termination Steps

1. **Stop the Main Script**:  
   If `main.py` is currently running, stop the script to halt the bot's operation.
    ```bash
    # Use Ctrl+C or the appropriate command to stop the script
    ```
    
2. **Run the Collection Script**:  
   Execute the `collection.py` script to collect your setup UTXOs.
    ```bash
    python3 collection.py
    ```

By following these steps, you'll terminate the bot and retrieve your setup UTXOs.

## Running Duckpools Off-Chain Bot as a Systemd Service
These steps will setup the off-chain-bot to run in the background upon startup and reboot automatically, unless you shut it down.

To ensure the Duckpools Off-Chain Bot starts automatically on system boot, you can set it up as a systemd service (Note: this is for a Linux setup). Follow these steps:

1. **Create a systemd Service File**

    Create a new service file named `duckpools-bot.service` in the `/etc/systemd/system/` directory.

    ```bash
    sudo nano /etc/systemd/system/duckpools-bot.service
    ```

2. **Configure the Service File**

    Add the following configuration to the service file. Be sure to replace <your-username> with your actual username and /path/to/your/off-chain-bot with the full path to your bot's directory.

    ```bash
    [Unit]
    Description=Duckpools Off-Chain Bot
    After=network.target

    [Service]
    User=<your-username>
    WorkingDirectory=/path/to/your/off-chain-bot
    ExecStart=/usr/bin/python3 main.py
    Restart=always
    Environment="API_KEY=your_api_key_value"
    Environment="WALLET_PASS=your_wallet_pass_value"

    [Install]
    WantedBy=multi-user.target
    ```
3. **Reload, Enable, Start**

    After saving the service file, reload the systemd daemon to apply the new service. Enable the service to start on boot, and then start the service immediately.

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable duckpools-bot.service
    sudo systemctl start duckpools-bot.service
    ```

4. **Verify the system is running**

    ```bash
    sudo systemctl status duckpools-bot.service
    ```

    **Note:** Ensure that python3 is the correct path for Python 3.x on your system. Adjust the ExecStart path as needed. The service file assumes that your main.py script is set up to run continuously or as a daemon.

5. **Check The Logs Realtime**
    To check the main.py output realtime, check the live logs using:
    
    ```bash
    sudo journalctl -fu duckpools-bot.service
    ```

### Disclaimer
By running this software, you assume all responsibility and risk associated with its operation. Users are to exercise caution and perform their own due diligence when running the bot, especially in a live environment.

The duckpools community welcomes contributions and feedback as we work towards enhancing the functionality and reliability of this project.
