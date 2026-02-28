# 🍽️ Serverless Dining Concierge (AWS)

A fully serverless restaurant recommendation chatbot built on AWS.  
The system collects user preferences via Amazon Lex and delivers curated restaurant suggestions via email.

## 👥 Team

- Devansh Vikram (dv2482)
- Shrutika Yadav (sy4790)

## 🏗️ Architecture Overview

This project uses the following AWS services:

- **Amazon Lex** – Conversational chatbot interface
- **AWS Lambda (LF1 & LF2)** – Backend logic and validation
- **Amazon SQS** – Decoupled message queue between Lex and processing layer
- **Amazon EventBridge** – Scheduled polling of SQS
- **Amazon OpenSearch** – Restaurant indexing and search
- **Amazon DynamoDB** – Restaurant metadata storage
- **Amazon SES** – Email delivery of dining suggestions

## ⚙️ System Flow

1. User interacts with chatbot (Lex).
2. LF1 validates slot inputs and pushes request to SQS.
3. EventBridge triggers LF2 periodically.
4. LF2 polls SQS, queries OpenSearch for restaurant IDs.
5. Detailed data is fetched from DynamoDB.
6. Suggestions are emailed to the user via SES.

## ✨ Features

- Real-time slot validation (city, cuisine, date, time, party size, email)
- NYC umbrella handling (New York / Manhattan / Brooklyn / Queens)
- Cuisine umbrella handling (Asian → Chinese/Japanese/Thai)
- Graceful failure handling for unsupported inputs
- Fully serverless and event-driven architecture

---

Built as part of an AWS-based cloud systems project.
