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
                    echo $PASS | docker login -u $dockeruser --password-stdin

                    docker push $IMAGE_NAME:$IMAGE_TAG
                    '''
                }
            }
        }

        stage('Deploy to Kubernetes') {

            steps {

                sh '''
                sed -i "s|latest|$IMAGE_TAG|g" k8s/deployment.yaml

                kubectl apply -f k8s/
                '''
            }
        }
    }
}
