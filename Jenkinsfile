pipeline {
//       ك أننا كنقولو لـ Jenkins: "خدم بهاد الـ Image ديال Python"
    agent {
        docker {
            image 'python:3.11-slim'
            // خاصنا نثبتو الأدوات لي محتاجين فكل build (أو نوجدو Docker image خاصة بينا)
            args '-u root' 
        }
    }

    environment {
        DOCKER_IMAGE     = 'lhassan1/truck-traffic-app:latest'
        AWS_REGION       = 'eu-west-3'
        DOCKER_HUB_CREDS = 'docker-hub-credentials'
        AWS_CREDS        = 'aws-credentials' 
        // Discord Webhook URL
        DISCORD_WEBHOOK  = 'https://discordapp.com/api/webhooks/1525547963554726182/W7xTdsguiYOn5vHla6lfzuJlkohts7FzVdWhBnwsOgIGQoGizZb1MMJba2YxRoYzKGke'
    }

    stages {
        stage('Checkout Code') {
            steps {
                checkout scm
            }
        }

        stage('Unit Testing') {
            steps {
                echo "Running Unit Tests..."
                // هنا كتشغل ليطيسط ديالك، تأكد بلي عندك pytest مثبة
               sh 'python3 -m pytest app/tests/'
            }
        }

        stage('Security Scan') {
            steps {
                echo "Running Security Scan with Trivy..."
                // غنخدمو بـ trivy باش نسكانيو الـ Dockerfile أو الكود
                sh 'trivy fs --exit-code 1 .' 
            }
        }

        stage('Terraform Init & Validate') {
            steps {
                script {
                    dir('terraform') {
                        withCredentials([usernamePassword(credentialsId: env.AWS_CREDS, passwordVariable: 'AWS_SECRET_ACCESS_KEY', usernameVariable: 'AWS_ACCESS_KEY_ID')]) {
                            // هادي غتخدم فكل Build باش تضمن باللي الـ Backend واجد
                            sh 'terraform init -input=false'
                            sh 'terraform validate'
                        }
                    }
                }
            }
        }

        stage('Docker Build & Push') {
            steps {
                script {
                    sh "docker build -t ${env.DOCKER_IMAGE} ./app"
                    withCredentials([usernamePassword(credentialsId: env.DOCKER_HUB_CREDS, passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER')]) {
                        sh "echo \$DOCKER_PASS | docker login -u \$DOCKER_USER --password-stdin"
                        sh "docker push ${env.DOCKER_IMAGE}"
                    }
                }
            }
        }

        stage('Terraform Apply') {
            steps {
                script {
                    dir('terraform') {
                        withCredentials([usernamePassword(credentialsId: env.AWS_CREDS, passwordVariable: 'AWS_SECRET_ACCESS_KEY', usernameVariable: 'AWS_ACCESS_KEY_ID')]) {
                            sh "terraform apply -var='app_docker_image=${env.DOCKER_IMAGE}' -auto-approve"
                        }
                    }
                }
            }
        }
    }

    post {
        success {
            script {
                def msg = "✅ Build Successful! The app is live."
                sh "curl -H 'Content-Type: application/json' -d '{\"content\": \"${msg}\"}' ${env.DISCORD_WEBHOOK}"
            }
        }
        failure {
            script {
                def msg = "❌ Build Failed! Please check Jenkins logs."
                sh "curl -H 'Content-Type: application/json' -d '{\"content\": \"${msg}\"}' ${env.DISCORD_WEBHOOK}"
            }
        }
    }
}
