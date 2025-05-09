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

 **Edit Client Constants**
   - Open `client_consts.py` in your text editor or nano.
   - Update the following parameters:
     - `node_url`: The URL of your Ergo node (e.g., `http://localhost:9053/`). 
     - `node_address`: Your node's main wallet address (e.g., `9fz...b32`).
   - Parameters that do not require updates:
     - `explorer_url`: Defaults to the standard explorer API URL.
     - `api_key`: Pre-configured and should not be changed.
     - `node_pass`: Pre-configured and should not be changed.
### Step 2: Setup & Execute `setup.py`

#### Secure Handling of Environment Variables

It's crucial to manage sensitive information such as API keys and passwords securely. One recommended approach is to use a `.duck_secrets` file in your home directory and source it when necessary. Below are the steps to set this up securely:

1. **Create the .duck_secrets File**

Create a `.duck_secrets` file in your home directory.
Ensure the file is readable only by your user to prevent unauthorized access:

```bash
cd
touch ~/.duck_secrets
chmod 600 ~/.duck_secrets
```

2. **Add Environment Variables to the `.duck_secrets` File**
Edit the `.duck_secrets` file and add your environment variables:

```bash
nano .duck_secrets
```
copy and paste the following into `.duck_secrets` file, update the strings inside the quotes.
```bash
export API_KEY="your_api_key_value"
export WALLET_PASS="your_wallet_pass_value"
```
Save and close the file.

3. **Source the `.duck_secrets` File When Needed**

Source the `.duck_secrets` file in your terminal session to load the environment variables:

```bash
source ~/.duck_secrets
```

4. **Automatically Source .duck_secrets in Your Session**

For automatic loading upon session start, add this snippet to your ~/.bashrc, ~/.bash_profile, or ~/.profile:

```bash
if [ -f ~/.duck_secrets ]; then
  source ~/.duck_secrets
fi
```

**Note:** Caution with Version Control
Ensure .duck_secrets is in your `.gitignore` file to prevent it from being tracked by version control systems. If the file doesn't exist, create it, and add `.duck_secrets` to the file.


5. **Run setup.py**
Finally, go to the directory with ~/off-chain-bot/setup.py and run it

Open your terminal and navigate to the folder where `setup.py` is located.

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
