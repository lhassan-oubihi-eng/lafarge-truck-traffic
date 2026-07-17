#!/bin/sh
echo "========= INITIALIZING MOCK SECRETS IN LOCALSTACK ========="
awslocal secretsmanager create-secret \
    --name "lafarge/truck-traffic/local/db" \
    --description "Local mock database credentials" \
    --secret-string '{"DB_HOST":"postgres","DB_PORT":"5432","DB_NAME":"lafarge","DB_USER":"postgres","DB_PASSWORD":"postgres"}'

awslocal secretsmanager create-secret \
    --name "lafarge/truck-traffic/local/aws" \
    --description "Local mock AWS credentials" \
    --secret-string '{"AWS_ACCESS_KEY_ID":"test","AWS_SECRET_ACCESS_KEY":"test"}'
echo "========= MOCK SECRETS CREATED SUCCESSFULLY ========="`
