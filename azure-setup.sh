#!/bin/bash
set -e   # stop on any error

GITHUB_USERNAME="mahd0x8"
RG="finance-rg"
LOCATION="eastus"
STORAGE="financestore$(date +%s | tail -c6)"   # unique suffix
APP="my-finance-app"
ENV="finance-env"

# GITHUB_PAT must be set in the environment before running:
#   export GITHUB_PAT=ghp_...
if [ -z "$GITHUB_PAT" ]; then
  echo "ERROR: set GITHUB_PAT before running (export GITHUB_PAT=ghp_...)"
  exit 1
fi

echo "==> Registering required providers..."
az provider register -n Microsoft.App --wait
az provider register -n Microsoft.OperationalInsights --wait

echo "==> Creating resource group..."
az group create --name $RG --location $LOCATION

echo "==> Creating storage account..."
az storage account create \
  --name $STORAGE \
  --resource-group $RG \
  --location $LOCATION \
  --sku Standard_LRS

echo "==> Creating file share for SQLite..."
az storage share create \
  --name financedata \
  --account-name $STORAGE

echo "==> Creating Container Apps environment..."
az containerapp env create \
  --name $ENV \
  --resource-group $RG \
  --location $LOCATION

echo "==> Fetching storage key..."
STORAGE_KEY=$(az storage account keys list \
  --account-name $STORAGE \
  --resource-group $RG \
  --query "[0].value" -o tsv)

echo "==> Registering Azure Files storage with the environment..."
az containerapp env storage set \
  --name $ENV \
  --resource-group $RG \
  --storage-name financedata \
  --azure-file-account-name $STORAGE \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name financedata \
  --access-mode ReadWrite

echo "==> Building & pushing Docker image..."
docker buildx create --use --name financebuilder 2>/dev/null || true
docker buildx build \
  --platform linux/amd64 \
  --push \
  -t ghcr.io/$GITHUB_USERNAME/finance-app:latest \
  .

echo "==> Deploying Container App with volume mount..."
az containerapp create \
  --name $APP \
  --resource-group $RG \
  --environment $ENV \
  --image ghcr.io/$GITHUB_USERNAME/finance-app:latest \
  --registry-server ghcr.io \
  --registry-username $GITHUB_USERNAME \
  --registry-password "$GITHUB_PAT" \
  --target-port 5000 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 1 \
  --env-vars DB_PATH=/data/finance.db \
  --volume-name financedata \
  --volume-storage-name financedata \
  --volume-storage-type AzureFile \
  --volume-mount-path /data

echo ""
echo "==> Creating service principal for GitHub Actions CI/CD..."
az ad sp create-for-rbac \
  --name "finance-app-deploy" \
  --role contributor \
  --scopes /subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG \
  --sdk-auth

echo ""
URL=$(az containerapp show --name $APP --resource-group $RG \
  --query properties.configuration.ingress.fqdn -o tsv)
echo "==> Done!"
echo "==> App URL: https://$URL"
echo "==> Copy the JSON above into GitHub secret: AZURE_CREDENTIALS"
echo "==> APP_NAME secret value: $APP"
echo "==> RESOURCE_GROUP secret value: $RG"
