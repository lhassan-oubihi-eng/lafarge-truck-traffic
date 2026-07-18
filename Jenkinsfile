pipeline {
    agent any

    environment {
        DISCORD_WEBHOOK_URL = credentials('discord-webhook-url')
        SONAR_TOKEN = credentials('sonar-token')
        SONAR_SCANNER_NAME = 'SonarScanner'
        AWS_DEFAULT_REGION = 'eu-west-3'
        AWS_ENDPOINT_URL = 'http://localstack:4566'
        // BUILD_NUMBER is already exported by Jenkins; Makefile picks it up for Docker tagging
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Code Quality') {
            steps {
                sh 'pip install pre-commit'
                sh 'pre-commit run --all-files'
            }
        }

        stage('Tests & Security Scans') {
            parallel {
                stage('Unit Testing') {
                    steps { sh 'make test' }
                }

                stage('Security Scan - Bandit') {
                    steps {
                        sh 'pip install bandit'
                        sh 'bandit -r app/ -ll'
                    }
                }

                stage('Security Scan - Trivy') {
                    steps { sh 'trivy fs --skip-db-update --exit-code 1 .' }
                }
            }
        }

        stage('SonarQube Analysis') {
            steps {
                script {
                    // Health check: wait for SonarQube to be ready
                    sh '''
                        echo "Waiting for SonarQube to be ready..."
                        for i in $(seq 1 30); do
                            if curl -sf "http://sonarqube-local:9000/api/system/health" > /dev/null 2>&1; then
                                echo "SonarQube is ready!"
                                break
                            fi
                            echo "Attempt $i/30 - SonarQube not ready yet, sleeping 5s..."
                            sleep 5
                        done
                    '''

                    def scannerHome = tool env.SONAR_SCANNER_NAME
                    withSonarQubeEnv(env.SONAR_SCANNER_NAME) {
                        sh """
                        ${scannerHome}/bin/sonar-scanner \
                        -Dsonar.projectKey=my-project \
                        -Dsonar.sources=. \
                        -Dsonar.host.url=http://sonarqube-local:9000 \
                        -Dsonar.token=${SONAR_TOKEN} \
                        -Dsonar.coverage.exclusions=**/*.tf,terraform/**/*.tf,**/Dockerfile,**/tests/**
                        """
                    }
                }
            }
        }

        stage('Terraform') {
            steps {
                withCredentials([
                    string(credentialsId: 'aws-access-key', variable: 'AWS_ACCESS_KEY_ID'),
                    string(credentialsId: 'aws-secret-key', variable: 'AWS_SECRET_ACCESS_KEY'),
                    string(credentialsId: 'DB_PASSWORD', variable: 'TF_VAR_db_password'),
                    string(credentialsId: 'DB_ROOT_PASSWORD', variable: 'TF_VAR_db_root_password')
                ]) {
                    sh '''
                        export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
                        export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
                        export TF_VAR_db_password=$TF_VAR_db_password
                        export TF_VAR_db_root_password=$TF_VAR_db_root_password
                        export TF_VAR_app_docker_image=lhassan1/truck-traffic-app:${BUILD_NUMBER}

                        make tf-init
                        make tf-validate
                        make tf-plan
                        make tf-apply-force
                    '''
                }
            }
        }

        stage('Docker & AWS Refresh') {
            steps {
                withCredentials([
                    usernamePassword(credentialsId: 'docker-hub-credentials', passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER'), // pragma: allowlist secret
                    string(credentialsId: 'aws-access-key', variable: 'AWS_ACCESS_KEY_ID'),
                    string(credentialsId: 'aws-secret-key', variable: 'AWS_SECRET_ACCESS_KEY')
                ]) {
                    sh '''
                        echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
                        make docker-push-hash
                        export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
                        export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
                        aws autoscaling start-instance-refresh --auto-scaling-group-name lafarge-truck-traffic-asg --region $AWS_DEFAULT_REGION || echo "Refresh already in progress, skipping..."
                    '''
                }
            }
        }
    }

    post {
        always {
            script {
                def status = currentBuild.currentResult
                def color = (status == 'SUCCESS') ? '3066993' : '15158332'
                sh """
                    curl -H "Content-Type: application/json" \
                    -X POST \
                    -d '{
                        "embeds": [{
                            "title": "Pipeline Build #${env.BUILD_NUMBER}",
                            "description": "Status: ${status}",
                            "url": "${env.BUILD_URL}",
                            "color": ${color},
                            "fields": [
                                {"name": "Project", "value": "lafarge-truck-traffic", "inline": true},
                                {"name": "Branch", "value": "${env.BRANCH_NAME ?: 'main'}", "inline": true}
                            ]
                        }]
                    }' \
                    $DISCORD_WEBHOOK_URL
                """
            }
        }
    }
}
