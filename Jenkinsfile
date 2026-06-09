pipeline {

    agent any

    environment {
        IMAGE_NAME = "ravi0619/flask-app"
        IMAGE_TAG = "1"
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Docker Image') {
            steps {
                sh 'docker build -t $flask-app:$v2 .'
            }
        }

        stage('Push Docker Image') {
            steps {

                withCredentials([
                    usernamePassword(
                        credentialsId: 'dockerhub-creds',
                        usernameVariable: 'ravi0619',
                        passwordVariable: 'Ravi_0619'
                    )
                ]) {

                    sh '''
                    echo $PASS | docker login -u $USER --password-stdin

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
