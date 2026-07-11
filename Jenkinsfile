pipeline {
    agent any

    stages {
        stage('Unit Testing') {
            steps {
                // دابا كيعيط لـ make test اللي زدنا
                sh 'make test'
            }
        }

        stage('Security Scan') {
            steps {
                // trivy كيبقى مستقل
                sh 'trivy fs --exit-code 1 .'
            }
        }

        stage('Terraform') {
            steps {
                sh 'make tf-init'
                sh 'make tf-validate'
                sh 'make tf-apply'
            }
        }

        stage('Docker & AWS Refresh') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'docker-hub-credentials', passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER')]) {
                    sh 'echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin'
                    // هادي كتجمع build + push + refresh ASG
                    sh 'make docker-push' 
                }
            }
        }
    }
}
