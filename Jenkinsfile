pipeline {
    agent any
    
    // تأكدي أن أدوات 'maven' أو 'SonarScanner' معرفة في Global Tool Configuration
    tools {
        maven 'maven' 
    }
    
    environment {
        DISCORD_WEBHOOK_URL = credentials('discord-webhook-url')
        SONAR_TOKEN = credentials('sonar-token')
        // اسم السيرفر الذي عرفتيه في Jenkins System
        SONAR_QUBE_SERVER = 'SonarQube' 
        AWS_DEFAULT_REGION = 'eu-west-3'
    }
    
    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Unit Testing') {
            steps { sh 'make test' }
        }

        stage('Security Scan') {
            steps { sh 'trivy fs --skip-db-update --exit-code 1 .' }
        }

       stage('SonarQube Analysis') {
    steps {
        script {
            // تأكدي أن 'SonarScanner' هو الاسم اللي عطيتي للـ Scanner في Global Tools
            def scannerHome = tool 'SonarScanner' 
            withSonarQubeEnv('SonarQube') { // 'SonarQube' هو اسم السيرفر في Manage Jenkins > System
                sh """
                ${scannerHome}/bin/sonar-scanner \
                -Dsonar.projectKey=my-project \
                -Dsonar.sources=. \
                -Dsonar.host.url=http://sonarqube-local:9000 \
                -Dsonar.login=${SONAR_TOKEN}
                """
            }
        }
    }
}

        stage('Terraform') {
            steps {
                withCredentials([
                    string(credentialsId: 'aws-access-key', variable: 'AWS_ACCESS_KEY_ID'),
                    string(credentialsId: 'aws-secret-key', variable: 'AWS_SECRET_ACCESS_KEY')
                ]) {
                    sh '''
                        export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
                        export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
                        make tf-init
                        make tf-validate
                        make tf-plan
                        make tf-apply
                    '''
                }
            }
        }

        stage('Docker & AWS Refresh') {
            steps {
                withCredentials([
                    usernamePassword(credentialsId: 'docker-hub-credentials', passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER'),
                    string(credentialsId: 'aws-access-key', variable: 'AWS_ACCESS_KEY_ID'),
                    string(credentialsId: 'aws-secret-key', variable: 'AWS_SECRET_ACCESS_KEY')
                ]) {
                    sh '''
                        echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
                        make docker-push
                        export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
                        export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
                        aws autoscaling start-instance-refresh --auto-scaling-group-name lafarge-truck-traffic-asg --region $AWS_DEFAULT_REGION
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
