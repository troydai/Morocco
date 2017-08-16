detail=$(az batch account list -otsv --query '[].{name:name, group:resourceGroup, ep: accountEndpoint}' | grep $1)
group=$(echo $detail | cut -f2 -d ' ')
endpoint="https://$(echo $detail | cut -f3 -d ' ')"

export AZURE_BATCH_ACCOUNT=$1
export AZURE_BATCH_ACCESS_KEY=$(az batch account keys list -n $1 -g $group -otsv --query 'secondary')
export AZURE_BATCH_ENDPOINT=$endpoint

