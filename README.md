# 🔌 Meter Readings Project

**Author:** Samuel Witt  
**Purpose:** Automate and analyze daily electricity meter readings using AWS services within the free tier.

---

## 📋 Project Overview

This project enables a streamlined workflow for uploading daily electricity meter readings to AWS, computing usage statistics, and storing structured data for analysis and as a backup solution.

I manually read my meter each day (peak and off-peak values), then trigger a Bash script on my phone via [Termux](https://termux.dev/). This script sends the readings to an AWS Lambda function that:

1. Retrieves the previous day's readings and tariff information from DynamoDB.
2. Calculates daily usage and cost.
3. Stores the processed reading in a DynamoDB table.
4. Optionally interpolates and inserts estimated values for skipped days.

---

## ✅ Features

- 📲 Easy mobile-based reading upload via a bash script on Termux
- ⚡ Peak and off-peak reading support
- 📅 Auto-filling skipped days with estimated usage
- 💰 Cost calculation based on configurable tariffs
- 🧠 Usage statistics computed in Lambda
- 🛠️ Easily extensible data schema

---

## 📐 System Architecture

- **Bash Script**: Handles sending meter readings to Lambda with curl
- **Lambda Function**: Handles API calls, processing readings and computing statistics.
- **DynamoDB Tables**:
  - `meter_readings`: Stores daily readings and calculated stats.
  - `tariff_info`: Holds current rate data for peak/off-peak pricing.


---

## 💸 AWS Free Tier Explanation

This project is designed to stay entirely within the AWS **always-free tier**, which is perfect for lightweight, low-traffic applications like manual daily meter readings.

- **AWS Lambda** provides 1 million free requests and 400,000 GB-seconds of compute time per month — more than enough to handle a daily Lambda call for this project.
- **DynamoDB** offers 25 GB of storage, 200 million requests per month (with up to 25 RCU and 25 WCU), and 2.5 million read/write requests via the on-demand capacity mode in the free tier.
- Optional services like **S3** and **QuickSight** can also be used in their free tiers with limitations (S3 offers 5 GB standard storage, and QuickSight has a limited free trial for one user).

By designing the Lambda function to be lightweight and only storing daily readings, this project comfortably fits within these limits, ensuring **no monthly cost**.

---
## 🔒 Security

To protect sensitive data, such as the AWS Lambda endpoint and API key, this project uses environment variables. This ensures that secrets are **never committed to version control (e.g., GitHub)**. The Bash script on the phone sources these environment variables locally, and the Lambda function reads them from its AWS-managed environment. This approach helps prevent accidental exposure and follows best practices for managing secrets in cloud-native applications.


---

## 📲 How I Upload Readings

1. Read my electricity meter manually.  
2. Open Termux on my Android phone.  
3. Run a Bash script that calls the AWS Lambda endpoint via curl, sending the current date, peak, and off-peak readings as query parameters or JSON payload.

---



## 🔧 Future Improvements

- [ ] Add a dashboard using AWS QuickSight
- [ ] Add average daily and nightly temperature values
- [ ] Add Telegram/WhatsApp bot integration for inputting readings  
- [ ] Add a web UI for manual entry and review  
- [ ] Create alerts if readings are missing for too long  
- [ ] Historical tariff support  

---

## 📂 Legacy Scripts

Old Python scripts for processing Octopus Energy account readings are located in the `manual_scripts/` folder. These were used before the current automated Lambda-based workflow.

---


## 🗃️ Data Tables (DynamoDB)

Meter readings table:

| Field             | Type     | Description                             |
|-------------------|----------|-----------------------------------------|
| `pk`              | string   | Primary key (`"reading"` for all items) |
| `date`            | string   | Date of the reading (YYYY-MM-DD)        |
| `peak`            | integer  | Cumulative peak reading                 |
| `off_peak`        | integer  | Cumulative off-peak reading             |
| `peak_usage`      | integer  | Peak usage on the day                   |
| `off_peak_usage`  | integer  | Off peak usage on the day               |
| `cost`            | float    | Total calculated cost for the day       |
| `is_estimated`    | boolean  | Indicates if the value was estimated    |

Tariff information table:

| Field             | Type    | Description                                       |
|-------------------|---------|---------------------------------------------------|
| `pk`              | string  | Primary key (`"tariff"` for all items)            |
| `start_date`      | string  | Start date of the tariff (YYYY-MM-DD)             |
| `peak_rate`       | float   | The cost of 1 KWH in the peak hours               |
| `off_peak_rate`   | float   | The cost of 1 KWH in the off peak hours           |
| `standing_charge` | float   | The daily cost to be connected to the energy grid |



---

## 📞 Contact

If you’re interested in setting up something similar or contributing improvements, feel free to reach out or fork the project!
