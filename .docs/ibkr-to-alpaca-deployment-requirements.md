# Deploy Alpaca Trading System to a New AWS EC2 Instance

I have tested the changes successfully in my local environment and am now ready to deploy the new version to a **new AWS EC2 instance**.

## Important Instructions

- **Do NOT execute any commands or make any changes.**
- I only want **step-by-step deployment instructions** that I can execute myself.
- Before providing the instructions, inspect the current repository and understand its deployment architecture, Docker configuration, environment variables, AWS/S3 usage, configuration files, startup process, scheduling, logging, and dependencies.
- Base the instructions on the **actual contents of this repository**, rather than giving generic AWS instructions.
- Identify anything I may have missed and include the necessary steps.
- Keep the new EC2 configuration as **simple and inexpensive as reasonably possible**, while still being reliable enough for automated trading.
- Clearly distinguish between commands I should execute locally, commands I should execute on the new EC2 instance, and AWS Console configuration.
- Do not assume that configuration files or secrets should be committed to GitHub. Explain how each sensitive configuration item should be transferred securely.
- Use **U.S. Eastern Time (`America/New_York`)** for all trading schedules and explicitly account for EST/EDT daylight-saving changes.
- Include verification steps before enabling live automated trading.

## Deployment Plan

Give me detailed instructions for the following:

### 1. Commit and Push the Tested Changes to GitHub

Provide steps to:

- Review the current Git status.
- Confirm that sensitive files are not being committed.
- Review `.gitignore` and recommend any necessary additions.
- Commit the tested Alpaca migration changes.
- Push the changes to GitHub.
- Verify that the correct commit is available in the remote repository.
- Identify the exact commit that should be deployed to EC2.

Also mention anything in the repository that should **not** be pushed to GitHub.

### 2. Create and Configure the New EC2 Instance

Give me step-by-step instructions for:

#### A. EC2 Instance Setup

Recommend the **smallest practical and cost-effective EC2 instance configuration** based on the requirements you discover in the repository.

Include:

- AWS region
- AMI / operating system
- Instance type
- Storage size
- Security group configuration
- Key pair / SSH access
- IAM role, if appropriate
- Whether a public IP is required
- Whether Elastic IP is necessary
- Any other required AWS configuration

Then provide instructions to:

- Create the instance.
- Connect to it using SSH.
- Update the operating system.
- Install required software such as Git, Docker, Docker Compose, unzip, and any other dependencies discovered in the repository.
- Clone the GitHub repository.
- Check out the exact production commit.
- Configure AWS access to the required S3 bucket using the **most secure and appropriate approach**, preferably an EC2 IAM role rather than storing AWS access keys on the instance.
- Configure API key and secret in `.env`.
- Configure accounts in `accounts.yaml`.
- Configure email in `config.py`.
- Configure any other required configuration files.
- Set appropriate file permissions for sensitive files.

Clearly identify which configuration values are sensitive.

### 4. Build and Start the Application

Provide instructions to:

- Build the Docker image(s), if applicable.
- Configure Docker Compose or the application's existing startup mechanism.
- Start the application manually for the first test.
- Check container/application status.
- Review application logs.
- Verify that the application can access S3.
- Verify that the Alpaca API connection works.
- Verify that all required market-data connections work.
- Verify that the application can read its configuration.

### 5. Create an EC2 Startup Script

Create instructions for implementing a startup mechanism so that the application automatically starts whenever the EC2 instance reboots.

Determine whether the repository should use:

- Docker restart policies,
- systemd,
- a startup script,
- or another mechanism.

Prefer the simplest reliable approach.

Include:

- Where the startup script/service should live.
- Exact commands to create/configure it.
- Required permissions.
- How to enable it.
- How to test it by rebooting the instance.
- How to verify that the application started successfully after reboot.
- How to prevent duplicate application instances from starting.

### 6. Scheduled Trading Execution

The application needs to run on a scheduled basis **Monday through Friday at 8:00 AM U.S. Eastern Time**.

Determine from the repository exactly what command/script should be scheduled.

Provide instructions to:

- Create the scheduled trading script if one does not already exist.
- Make it executable.
- Configure the schedule.
- Configure the cron job or recommend a better mechanism if appropriate.
- Ensure the schedule correctly handles **EST/EDT daylight-saving changes**.
- Ensure the job does not accidentally run twice.
- Ensure the job does not overlap with a previous execution.
- Capture stdout/stderr to appropriate log files.
- Ensure the scheduled job runs with the correct environment variables and working directory.
- Verify the cron configuration.
- Manually test the scheduled command before enabling the live schedule.

Explicitly explain how the schedule behaves during U.S. daylight-saving changes.

### 7. Logging and Log Management

Design a simple, low-cost logging solution appropriate for this EC2 instance.

Include:

#### Log Rotation

- Identify which application/container/cron logs are generated.
- Create an appropriate log rotation configuration.
- Prevent logs from filling the EC2 disk.
- Specify retention period and maximum log size.
- Explain how to verify log rotation.

#### Monitoring Script

Create instructions for a lightweight monitoring script that can detect problems such as:

- Application/container not running.
- Scheduled process failed.
- Docker container exited unexpectedly.
- Disk usage becoming too high.
- Important application errors.
- Authentication/API connection failures, if detectable from logs.

Explain how the monitoring script should notify me if a problem is detected.

Prefer a simple, inexpensive solution rather than introducing unnecessary AWS services.

### 8. AWS/EC2 Security

Include a security checklist covering:

- IAM role and least-privilege access.
- S3 permissions.
- EC2 security group.
- SSH access.
- `.env` and `accounts.yaml` permissions.
- Alpaca API keys.
- GitHub credentials.
- AWS credentials.
- Secrets accidentally appearing in logs.
- Whether any ports need to be exposed publicly.
- Whether SSH should be restricted to my IP.
- Any Docker security considerations.

### 9. Testing and Verification

Provide a comprehensive verification procedure before switching production trading to the new EC2 instance.

Include:

#### Infrastructure

- EC2 connectivity.
- Docker status.
- Disk space.
- Memory/CPU.
- Internet connectivity.
- S3 access.

#### Application

- Configuration loading.
- Alpaca authentication.
- Market-data connectivity.
- Application startup.
- Docker/container health.
- Logs.

#### Scheduling

- Cron configuration.
- Manual execution.
- Scheduled execution.
- EST/EDT behavior.
- Duplicate execution prevention.

#### Trading Safety

Before enabling live trading, verify:

- Correct Alpaca account.
- Correct account configuration.
- Correct symbols.
- Correct strategy configuration.
- Correct position sizing.
- Correct buy/sell logic.
- No IBKR connection remains.
- No old IBKR process is running.
- No duplicate trading process exists.
- No unexpected orders are generated.

If the application supports a paper-trading mode, explain how to use it for final verification before enabling live trading.


## Output Format

I want **instructions only**, not execution.

Organize the response as:

1. **Pre-Deployment Review**
2. **GitHub Commit and Push**
3. **Old IBKR EC2 Transition**
4. **New EC2 Creation**
5. **EC2 Software Installation**
6. **Repository Deployment**
7. **AWS/S3 Configuration**
8. **Application Configuration**
9. **Application Startup**
10. **Startup-on-Reboot Configuration**
11. **Scheduled Trading Configuration**
12. **Logging and Log Rotation**
13. **Monitoring**
14. **Security Configuration**
15. **Testing and Verification**
16. **Final Production Checklist**

For commands, provide the **exact commands I should run**, but do not execute them.

For every command, clearly indicate whether it should be run:

- **[LOCAL]** — on my development computer
- **[EC2]** — on the new EC2 instance
- **[AWS CONSOLE]** — in the AWS Console

If you discover that the repository already contains scripts/configuration for any of these functions, use those existing mechanisms rather than creating unnecessary new ones.

Finally, identify **anything important I have overlooked** in this deployment plan and add it to the instructions.