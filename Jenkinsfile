pipeline {
    agent any

    environment {
        // السمية د الـ Image ديالك ف Docker Hub
        DOCKER_IMAGE   = 'lhassan1/truck-traffic-app:latest'
        AWS_REGION     = 'eu-west-3'
        // الـ ID د الـ Credentials لي مخبيين ف Jenkins
        DOCKER_HUB_CREDS = 'docker-hub-credentials'
        AWS_CREDS        = 'aws-credentials' 
    }

    stages {
        stage('Checkout Code') {
            steps {
                // سحب آخر التحديثات من المستودع
                checkout scm
            }
        }

        stage('Docker Build & Push') {
            steps {
                script {
                    echo "Starting Docker Build for ${env.DOCKER_IMAGE}..."
                    // بناء الصورة من المجلد فين كاين الـ Dockerfile (مثلا ./app)
                    sh "docker build -t ${env.DOCKER_IMAGE} ./app"
                    
                    echo "Logging into Docker Hub and Pushing Image..."
                    // تسجيل الدخول ورفع الصورة أوتوماتيكياً
                    withCredentials([usernamePassword(credentialsId: env.DOCKER_HUB_CREDS, passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER')]) {
                        sh "echo \$DOCKER_PASS | docker login -u \$DOCKER_USER --password-stdin"
                        sh "docker push ${env.DOCKER_IMAGE}"
                    }
                }
            }
        }

        stage('Terraform Init & Validate') {
            steps {
                script {
                    dir('terraform') {
                        // تمرير الـ AWS Credentials للـ Terraform باش يقدر يوصل للـ S3 Backend والـ AWS API
                        withCredentials([usernamePassword(credentialsId: env.AWS_CREDS, passwordVariable: 'AWS_SECRET_ACCESS_KEY', usernameVariable: 'AWS_ACCESS_KEY_ID')]) {
                            sh 'terraform init'
                            sh 'terraform validate'
                        }
                    }
                }
            }
        }

        stage('Terraform Apply / Deploy') {
            steps {
                script {
                    dir('terraform') {
                        withCredentials([usernamePassword(credentialsId: env.AWS_CREDS, passwordVariable: 'AWS_SECRET_ACCESS_KEY', usernameVariable: 'AWS_ACCESS_KEY_ID')]) {
                            echo "Applying Terraform changes..."
                            // الـ apply كيدوز أوتوماتيكيا وبلا ما يطلب التقرير بـ -auto-approve
                            sh "terraform apply -var='app_docker_image=${env.DOCKER_IMAGE}' -auto-approve"
                        }
                    }
                }
            }
        }
    }

    post {
        success {
            echo "SUCCESS: The traffic management application has been deployed successfully!"
        }
        failure {
            echo "FAILURE: Something went wrong in the pipeline. Check the logs above."
        }
    }
}
