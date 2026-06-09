pipeline {

    agent any

    environment {
        IMAGE_NAME = "ravi0619/flask-app"
        IMAGE_TAG = "v2"
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Docker Image') {
            steps {
                sh 'docker build -t $IMAGE_NAME:$IMAGE_TAG .'
            }
        }

        stage('Push Docker Image') {
            steps {

                withCredentials([
                    usernamePassword(
                        credentialsId: 'dockerhub-creds',
                        usernameVariable: 'dockeruser',
                        passwordVariable: 'dockerpass'
                    )
                ]) {

                    sh '''
            echo "USER=$dockeruser"

            if [ -z "$dockerpass" ]; then
                echo "PASSWORD EMPTY"
                exit 1
            else
                echo "PASSWORD FOUND"
            fi
            '''
                }
            }
        }

        stage('Deploy to Kubernetes') {

            steps {

                sh '''
                sed -i "s|latest|$IMAGE_TAG|g" deployment.yaml

                kubectl apply -f deployments.yaml
                kubectl apply -f service.yaml
                '''
            }
        }
    }
}
