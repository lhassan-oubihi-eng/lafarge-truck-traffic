// ============================================================================
// Jenkinsfile - Lafarge Truck Traffic Management
// Pipeline CI/CD : build & push de l'image Docker, puis déploiement de
// l'infrastructure AWS (ALB + Auto Scaling Group) via Terraform.
//
// Credentials Jenkins requis (à créer dans "Manage Jenkins > Credentials") :
//   - "dockerhub-credentials"   : Username/Password vers Docker Hub (ou ECR)
//   - "aws-credentials"         : AWS Access Key ID / Secret Access Key
//                                 (type "AWS Credentials" du plugin AWS)
//
// PRÉREQUIS UNIQUE (à faire une seule fois, manuellement, avant le tout
// premier build de ce pipeline) : le bucket S3 et la table DynamoDB du
// backend distant Terraform doivent déjà exister, car "terraform init"
// dans ce pipeline s'y connecte directement (backend "s3" défini en dur
// dans terraform/main.tf). Les créer avec :
//   cd terraform/bootstrap && terraform init && terraform apply
// ============================================================================

pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        DOCKERHUB_REPO   = "lafargeholcim/truck-traffic-app"
        IMAGE_TAG        = "${env.BUILD_NUMBER}"
        TERRAFORM_DIR    = "terraform"
        APP_DIR          = "app"
        AWS_DEFAULT_REGION = "eu-west-3"
    }

    stages {

        stage('Checkout') {
            steps {
                echo "Récupération du code source depuis le dépôt Git..."
                checkout scm
            }
        }

        stage('Build Docker Image') {
            steps {
                dir("${APP_DIR}") {
                    echo "Construction de l'image Docker de l'application..."
                    sh """
                        docker build -t ${DOCKERHUB_REPO}:${IMAGE_TAG} .
                        docker tag ${DOCKERHUB_REPO}:${IMAGE_TAG} ${DOCKERHUB_REPO}:latest
                    """
                }
            }
        }

        stage('Push Docker Image') {
            steps {
                echo "Publication de l'image sur le registre Docker..."
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-credentials',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh """
                        echo "\$DOCKER_PASS" | docker login -u "\$DOCKER_USER" --password-stdin
                        docker push ${DOCKERHUB_REPO}:${IMAGE_TAG}
                        docker push ${DOCKERHUB_REPO}:latest
                        docker logout
                    """
                }
            }
        }

        stage('Terraform Init') {
            steps {
                dir("${TERRAFORM_DIR}") {
                    withCredentials([[
                        $class: 'AmazonWebServicesCredentialsBinding',
                        credentialsId: 'aws-credentials'
                    ]]) {
                        sh "terraform init -input=false"
                    }
                }
            }
        }

        stage('Terraform Validate & Plan') {
            steps {
                dir("${TERRAFORM_DIR}") {
                    withCredentials([[
                        $class: 'AmazonWebServicesCredentialsBinding',
                        credentialsId: 'aws-credentials'
                    ]]) {
                        sh """
                            terraform validate
                            terraform plan \
                                -input=false \
                                -var="app_docker_image=${DOCKERHUB_REPO}:${IMAGE_TAG}" \
                                -out=tfplan
                        """
                    }
                }
            }
        }

        stage('Approval') {
            when {
                branch 'main'
            }
            steps {
                // Validation manuelle avant application en production.
                // Timeout de sécurité pour ne pas bloquer indéfiniment le pipeline.
                timeout(time: 15, unit: 'MINUTES') {
                    input message: "Valider le déploiement en production sur AWS ?", ok: "Déployer"
                }
            }
        }

        stage('Terraform Apply') {
            steps {
                dir("${TERRAFORM_DIR}") {
                    withCredentials([[
                        $class: 'AmazonWebServicesCredentialsBinding',
                        credentialsId: 'aws-credentials'
                    ]]) {
                        sh "terraform apply -input=false -auto-approve tfplan"
                    }
                }
            }
        }

        stage('Rolling Update ASG') {
            steps {
                // Déclenche un instance refresh pour que les instances existantes
                // récupèrent la nouvelle image Docker, sans coupure de service
                // (grâce à la stratégie Rolling définie dans le Launch Template).
                dir("${TERRAFORM_DIR}") {
                    withCredentials([[
                        $class: 'AmazonWebServicesCredentialsBinding',
                        credentialsId: 'aws-credentials'
                    ]]) {
                        script {
                            def asgName = sh(
                                script: "terraform output -raw autoscaling_group_name",
                                returnStdout: true
                            ).trim()

                            sh """
                                aws autoscaling start-instance-refresh \
                                    --auto-scaling-group-name ${asgName} \
                                    --preferences '{"MinHealthyPercentage": 50, "InstanceWarmup": 60}'
                            """
                        }
                    }
                }
            }
        }

        stage('Smoke Test') {
            steps {
                dir("${TERRAFORM_DIR}") {
                    script {
                        def albDns = sh(
                            script: "terraform output -raw alb_dns_name",
                            returnStdout: true
                        ).trim()

                        echo "Vérification de la disponibilité de l'application sur http://${albDns}/healthz"
                        sh """
                            for i in \$(seq 1 10); do
                                if curl -sf http://${albDns}/healthz; then
                                    echo "Application disponible."
                                    exit 0
                                fi
                                echo "Application pas encore prête, nouvelle tentative dans 15s..."
                                sleep 15
                            done
                            echo "L'application n'a pas répondu après 10 tentatives."
                            exit 1
                        """
                    }
                }
            }
        }
    }

    post {
        success {
            echo "Déploiement réussi. Le tableau de bord Truck Traffic est disponible via l'ALB."
        }
        failure {
            echo "Échec du pipeline. Consultez les logs ci-dessus pour diagnostiquer l'étape en erreur."
        }
        always {
            dir("${TERRAFORM_DIR}") {
                sh "rm -f tfplan || true"
            }
            sh "docker system prune -f || true"
        }
    }
}
