#!/bin/bash
# Run this once to create all Azure resources.
# Fill in the variables below before running.

GITHUB_USERNAME="mahd0x8"   # e.g. mahd
RG="finance-rg"
LOCATION="eastus"
STORAGE="financestorage$RANDOM"          # must be globally unique
APP="my-finance-app"
ENV="finance-env"

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

echo "==> Deploying Container App (first deploy)..."
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
  --env-vars DB_PATH=/data/finance.db

echo "==> Mounting Azure Files volume for SQLite..."
az containerapp update \
  --name $APP \
  --resource-group $RG \
  --storage-name financestorage \
  --storage-account-name $STORAGE \
  --storage-account-key $STORAGE_KEY \
  --storage-share-name financedata \
  --storage-mount-path /data \
  --storage-access-mode ReadWrite

echo ""
echo "==> Creating Azure service principal for GitHub Actions..."
az ad sp create-for-rbac \
  --name "finance-app-deploy" \
  --role contributor \
  --scopes /subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG \
  --sdk-auth

echo ""
echo "==> Done! Copy the JSON above into GitHub secret: AZURE_CREDENTIALS"
echo "==> App name for GitHub secret APP_NAME: $APP"
echo "==> Resource group for GitHub secret RESOURCE_GROUP: $RG"
