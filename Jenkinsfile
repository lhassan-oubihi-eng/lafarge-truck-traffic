pipeline {
    agent any

    stages {
        stage('Unit Testing') {
            steps {
                // دابا كيعيط لـ make test: اللي زدنا
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
                withCredentials([string(credentialsId: 'aws-access-key', variable: 'AWS_ACCESS_KEY_ID'),
                                 string(credentialsId: 'aws-secret-key', variable: 'AWS_SECRET_ACCESS_KEY')]) {
                    sh 'make tf-init'
                    sh 'make tf-validate'
                    // هنا كنعيطو لـ plan باش يتصاوب ملف tfplan
                    sh 'make tf-plan'
                    // هنا كنعيطو لـ apply اللي كيستعمل داك الملف
                    sh 'make tf-apply'
                }
            }
        }	

	stage('Docker & AWS Refresh') {
            steps {
                // ندمجو الـ Credentials ديال Docker و AWS في نفس البلوك
                withCredentials([
                    usernamePassword(credentialsId: 'docker-hub-credentials', passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER'),
                    string(credentialsId: 'aws-access-key', variable: 'AWS_ACCESS_KEY_ID'),
                    string(credentialsId: 'aws-secret-key', variable: 'AWS_SECRET_ACCESS_KEY')
                ]) {
                    // 1. Login Docker
                    sh 'echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin'
                    
                    // 2. Push Docker image
                    sh 'make docker-push'
                    
                    // 3. Refresh AWS ASG (مع تمرير الـ Credentials لـ AWS CLI)
                    sh '''
                        export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
                        export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
                        export AWS_DEFAULT_REGION=eu-west-3
                        make aws-refresh
                    '''
                }
            }
        }
    }
}
