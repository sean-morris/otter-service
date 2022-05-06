# Kubernetes config:
NAMESPACE=`kubectl config view --minify --output 'jsonpath={..namespace}'`

SA_KUBE=$(kubectl get serviceaccounts 2>&1)
if [[ ! $SA_KUBE =~ "gofer-k8-sa" ]]; then
    kubectl create serviceaccount --namespace $NAMESPACE gofer-k8-sa
fi

#GCP config:
SA_OUTPUT=$(gcloud iam service-accounts describe gofer-sa@data8x-scratch.iam.gserviceaccount.com 2>&1)
if [[ $SA_OUTPUT =~ "Unknown service account" ]] || [[ $SA_OUTPUT =~ "PERMISSION_DENIED" ]]; then
    gcloud iam service-accounts create gofer-sa
fi

# #Add all the roles we need:
gcloud projects add-iam-policy-binding data8x-scratch \
    --member "serviceAccount:gofer-sa@data8x-scratch.iam.gserviceaccount.com" \
    --role "roles/editor" \
    --no-user-output-enabled

gcloud projects add-iam-policy-binding -q data8x-scratch \
    --member "serviceAccount:gofer-sa@data8x-scratch.iam.gserviceaccount.com" \
    --role "roles/cloudkms.cryptoKeyEncrypterDecrypter" \
    --no-user-output-enabled


#Tie the K8 SA to GCloud SA:
#Allow impersonation:
gcloud iam service-accounts add-iam-policy-binding -q gofer-sa@data8x-scratch.iam.gserviceaccount.com \
    --role roles/iam.workloadIdentityUser \
    --member "serviceAccount:data8x-scratch.svc.id.goog[$NAMESPACE/gofer-k8-sa]" \
    --no-user-output-enabled


#Annotate the K8 Service account:
kubectl annotate serviceaccount \
        --namespace $NAMESPACE gofer-k8-sa \
        --overwrite \
        iam.gke.io/gcp-service-account=gofer-sa@data8x-scratch.iam.gserviceaccount.com
