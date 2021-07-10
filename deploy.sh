

#!/bin/bash
# debug
# set -o xtrace

KEY_NAME="caching-cloud-`date +'%N'`"
KEY_PEM="$KEY_NAME.pem"

STACK_NAME="caching-stack"
REGION=us-east-1

#Creating .pem file
echo "create key pair $KEY_PEM to connect to instances and save locally"
aws ec2 create-key-pair --key-name $KEY_NAME  --query "KeyMaterial" --output text > $KEY_PEM

# Secure the key pair
chmod 600 $KEY_PEM

# Figure out my ip
MY_IP=$(curl ipinfo.io/ip)
echo "My IP: $MY_IP"


# get subnets for the ELB and vpc id
echo "get all the network parameters"
SUB_ID_1=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[0] | jq -r .SubnetId)
SUB_ID_2=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[1] | jq -r .SubnetId)
SUB_ID_3=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[2] | jq -r .SubnetId)
SUB_ID_4=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[3] | jq -r .SubnetId)
VPC_ID=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[0] | jq -r .VpcId)
VPC_CIDR_BLOCK=$(aws ec2 describe-vpcs --filters Name=vpc-id,Values=$VPC_ID | jq -r .Vpcs[0].CidrBlock)


echo "creating stack $STACK_NAME"
STACK_RES=$(aws cloudformation create-stack --stack-name $STACK_NAME --template-body file://ec2CloudFormation.yml --capabilities CAPABILITY_NAMED_IAM \
	--parameters ParameterKey=InstanceType,ParameterValue=t2.micro \
	ParameterKey=KeyName,ParameterValue=$KEY_NAME \
	ParameterKey=SSHLocation,ParameterValue=$MY_IP/32 \
	ParameterKey=SubNetId1,ParameterValue=$SUB_ID_1 \
	ParameterKey=SubNetId2,ParameterValue=$SUB_ID_2 \
	ParameterKey=SubNetId3,ParameterValue=$SUB_ID_3 \
	ParameterKey=SubNetId4,ParameterValue=$SUB_ID_4 \
	ParameterKey=VPCId,ParameterValue=$VPC_ID \
	ParameterKey=VPCcidr,ParameterValue=$VPC_CIDR_BLOCK)

echo "waiting for stack $STACK_NAME to be created - this might take some time"
STACK_ID=$(echo $STACK_RES | jq -r '.StackId')
aws cloudformation wait stack-create-complete --stack-name $STACK_ID


#get stack
STACK=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME | jq -r .Stacks[0])

# stack outputs
OUTPUTS=$(echo $STACK | jq -r .Outputs)


echo "getting instances IP's"
IP_1=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='Instance1IP'].OutputValue" --output text)
echo "IP_1: $IP_1"
IP_2=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='Instance2IP'].OutputValue" --output text)
echo "IP_2: $IP_2"
IP_3=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='Instance3IP'].OutputValue" --output text)
echo "IP_3: $IP_3"
IP_4=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='Instance4IP'].OutputValue" --output text)
echo "IP_4: $IP_4"


ID1=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='InstanceId1'].OutputValue" --output text)
ID2=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='InstanceId2'].OutputValue" --output text)
ID3=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='InstanceId3'].OutputValue" --output text)
ID4=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='InstanceId4'].OutputValue" --output text)
TGARN=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='TargetGroup'].OutputValue" --output text)



echo "checking all instances"
aws ec2 wait instance-status-ok --instance-ids $ID1
echo "Instance 1 is working"
aws ec2 wait instance-status-ok --instance-ids $ID2
echo "Instance 2 is working"
aws ec2 wait instance-status-ok --instance-ids $ID3
echo "Instance 3 is working"
aws ec2 wait instance-status-ok --instance-ids $ID4
echo "Instance 4 is working"

echo "waiting for instances to wake up properly and connect to ELB"
aws elbv2 describe-target-health  --target-group-arn $TGARN

echo "getting IP address"
IP_ADDRESS=$(aws elbv2 describe-load-balancers --names cachingELB | jq -r .LoadBalancers[0].DNSName)

curl -X GET "@$IP_ADDRESS/health-check"

echo "access the ELB with IP address:"
echo $IP_ADDRESS

echo "done deploy"

