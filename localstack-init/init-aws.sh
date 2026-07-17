#!/bin/sh
set -e

# Required environment variables for LocalStack mock secrets
DB_HOST="${DB_HOST:?DB_HOST environment variable is required}"
DB_PORT="${DB_PORT:?DB_PORT environment variable is required}"
DB_NAME="${DB_NAME:?DB_NAME environment variable is required}"
DB_USER="${DB_USER:?DB_USER environment variable is required}"
DB_PASSWORD="${DB_PASSWORD:?DB_PASSWORD environment variable is required}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID environment variable is required}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY environment variable is required}"

echo "========= INITIALIZING MOCK SECRETS IN LOCALSTACK ========="
awslocal secretsmanager create-secret \
    --name "lafarge/truck-traffic/local/db" \
    --description "Local mock database credentials" \
    --secret-string "{\"DB_HOST\":\"${DB_HOST}\",\"DB_PORT\":\"${DB_PORT}\",\"DB_NAME\":\"${DB_NAME}\",\"DB_USER\":\"${DB_USER}\",\"DB_PASSWORD\":\"${DB_PASSWORD}\"}"

awslocal secretsmanager create-secret \
    --name "lafarge/truck-traffic/local/aws" \
    --description "Local mock AWS credentials" \
    --secret-string "{\"AWS_ACCESS_KEY_ID\":\"${AWS_ACCESS_KEY_ID}\",\"AWS_SECRET_ACCESS_KEY\":\"${AWS_SECRET_ACCESS_KEY}\"}"
echo "========= MOCK SECRETS CREATED SUCCESSFULLY ========="
