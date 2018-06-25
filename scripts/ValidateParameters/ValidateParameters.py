import json
import boto3
import cfnresponse
from netaddr import IPNetwork, IPAddress
 

responseStr = {'Status' : {}}
routeTableID = ""

def ip_in_subnetwork(ip_address, subnetwork):
  if IPAddress(ip_address) in IPNetwork(subnetwork):
    return True
  else:
    return False

def check_duplicate_virtual_ip(routeTableID,virtualip):
    ec2client = boto3.client('ec2')
    response = ec2client.describe_route_tables(RouteTableIds=[routeTableID])
    for destination in response['RouteTables'][0]['Routes']:
        if 'DestinationCidrBlock' in destination:
            if destination['DestinationCidrBlock'].split('/')[0] == virtualip:
                return True
    return False

def count_instances_by_tagkey(tagkey):            
    ec2client = boto3.client('ec2')            
    response = ec2client.describe_instances(Filters=[{'Name':'tag-key', 'Values':[tagkey]}])
    return len(response["Reservations"])

def get_main_route_table(vpcId):
    ec2client = boto3.client('ec2')
    response = ec2client.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpcId]},{'Name': 'association.main', 'Values': ['true',]}])
    return response['RouteTables'][0]['Associations'][0]['RouteTableId']

def get_route_table(subnet,vpcId):
    global routeTableID
    ec2 = boto3.client('ec2')
    retValue = ec2.describe_route_tables(Filters=[{'Name': 'association.subnet-id', 'Values': [subnet]}])
    if len(retValue['RouteTables']) > 0 :
       routeTableID = retValue['RouteTables'][0]['Associations'][0]['RouteTableId']
       return routeTableID
    else:
       routeTableID = get_main_route_table(vpcId)
       return routeTableID
       
def validate_common_route_table(subnet1, subnet2,vpcId):
   if ( get_route_table(subnet1,vpcId) == get_route_table(subnet2,vpcId) ):
       return True
   else:
       return False

def get_vpc_CIDR(vpcId):
    ec2 = boto3.client('ec2')
    retValue = ec2.describe_vpcs(VpcIds=[vpcId])
    return retValue['Vpcs'][0]['CidrBlock']

def handler(input, context):
    print('Received event: %s' % json.dumps(input))
    status = cfnresponse.SUCCESS
    try:
        subnet1 = input['ResourceProperties']['PrimarySubnetId']
        subnet2 = input['ResourceProperties']['SecondarySubnetId']
        tagkey = input['ResourceProperties']['PaceMakerTag']
        virtualip = input['ResourceProperties']['VirtualIP']
        vpcId = input['ResourceProperties']['VPCID']
        vpcCIDR = get_vpc_CIDR(vpcId)
        print("VPC CIDR is  " + vpcCIDR)

        if (input['RequestType'] == "Update") or (input['RequestType'] == "Create"):

            if count_instances_by_tagkey(tagkey) > 0:
              #Tag already exists and not unique
              responseStr["Status"]["ValidateParametersLambda"] =  "Tag not unique"       
              cfnresponse.send(input, context, cfnresponse.FAILED, {'Status':'Tag not unique'})
              return 

            if ip_in_subnetwork(virtualip,vpcCIDR):
              #IP Address in VPC CIDR
              responseStr["Status"]["ValidateParametersLambda"] =  "Virtual IP address should not be in VPC CIDR"       
              cfnresponse.send(input, context, cfnresponse.FAILED, {'Status':'Virtual IP address should not be in VPC CIDR'})  
              return 
          
            if not validate_common_route_table(subnet1, subnet2,vpcId):
              #Route Table not common
              responseStr["Status"]["ValidateParametersLambda"] =  "Primary and Secondary Subnet must have same route table"       
              cfnresponse.send(input, context, cfnresponse.FAILED, {'Status':'Primary and Secondary Subnet must have same route table'}) 
              return 
            
            if check_duplicate_virtual_ip(routeTableID,virtualip):
              #Virtual IP already in usage
              responseStr["Status"]["ValidateParametersLambda"] =  "Virtual IP is already being used (in Route Table of Subnet)"       
              cfnresponse.send(input, context, cfnresponse.FAILED, {'Status':'Virtual IP is already being used (in Route Table of Subnet)'})  
              return 

            responseStr["Status"]["ValidateParametersLambda"] =  "Success"       
            cfnresponse.send(input, context, cfnresponse.SUCCESS, {'Status':json.dumps(responseStr)})
        
        else:
            responseStr['Status'] = 'Nothing to do as Request Type is : ' + input['RequestType']
            cfnresponse.send(input, context, cfnresponse.SUCCESS, {'Status':json.dumps(responseStr)})
    except Exception as e:
        responseStr['Status']['ValidateParametersLambda'] = str(e)
        cfnresponse.send(input, context, cfnresponse.FAILED, {'Status':json.dumps(responseStr)})