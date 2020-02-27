import cfnresponse
import json
import boto3
import time
import sys
import jmespath

# responseStr = {'Status' : {}}
responseStr = {}


def updateNetworkConfig(HANAInstanceID,HANAIPAddress,HANAIP2Address,AWSRegion):
    CommandArray = []
    CommandArray.append('sed -i".bak" "/CLOUD_NETCONFIG_MANAGE/d" /etc/sysconfig/network/ifcfg-eth0')
    CommandArray.append('echo -e "CLOUD_NETCONFIG_MANAGE=\'no\'">> /etc/sysconfig/network/ifcfg-eth0')
    CommandArray.append('echo -e "IPADDR_1=\''+HANAIP2Address+'\'" >> /etc/sysconfig/network/ifcfg-eth0')
    CommandArray.append('echo -e "LABEL_1=\'1\'" >> /etc/sysconfig/network/ifcfg-eth0')
    CommandArray.append('ifup eth0')
    CommandArray.append('service network restart')
    CommandArray.append('service amazon-ssm-agent stop')
    CommandArray.append('service amazon-ssm-agent start')    
    CommandArray.append('echo "done"')
    CommentStr = 'Network config'
    InstanceIDArray =[HANAInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def backupHANAonPrimary(HANAPrimaryInstanceID,hanaSID,hanaInstanceNo,HANAMasterPass,AWSRegion):
    CommandArray = []
    CommandArray.append('HANAVersion='+'`su - '+hanaSID.lower()+'adm -c "HDB version | grep version:"`')
    CommandArray.append('HANAVersion=`echo $HANAVersion | awk \'{print $2}\' |  awk -F\'.\' \'{print $1}\'`')
    CommandArray.append('if [[ $HANAVersion -ne 1 ]]')
    CommandArray.append('then')
    CommandArray.append('echo $HANAVersion')
    CommandArray.append('su - '+hanaSID.lower()+'adm -c "hdbsql -u system -i '+hanaInstanceNo+' -d SystemDB -p '+HANAMasterPass+' \\"BACKUP DATA FOR SystemDB  USING FILE (\'backupSystem\')\\""')    
    CommandArray.append('su - '+hanaSID.lower()+'adm -c "hdbsql -u system -i '+hanaInstanceNo+' -d SystemDB -p '+HANAMasterPass+' \\"BACKUP DATA FOR '+hanaSID+' USING FILE (\'backup'+hanaSID+'\')\\""')
    CommandArray.append('else')
    CommandArray.append('su - '+hanaSID.lower()+'adm -c "hdbsql -u system -i '+hanaInstanceNo+' -p '+HANAMasterPass+' \\"BACKUP DATA USING FILE (\'backupDatabase\')\\""')    
    CommandArray.append('fi')
    CommentStr = 'Backup Database on Primary'
    InstanceIDArray =[HANAPrimaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion):
    session = boto3.Session()
    ssmClient = session.client('ssm', region_name=AWSRegion)
    ssmCommand = ssmClient.send_command(
                InstanceIds=InstanceIDArray,
                DocumentName='AWS-RunShellScript',
                TimeoutSeconds=30,
                Comment=CommentStr,
                Parameters={
                        'commands': CommandArray
                    }
                )
    L_SSMCommandID = ssmCommand['Command']['CommandId']
    status = 'Pending'
    while status == 'Pending' or status == 'InProgress':
        status = (ssmClient.list_commands(CommandId=L_SSMCommandID))['Commands'][0]['Status']
        time.sleep(3)

    if (status == "Success"):
        #response = ssmClient.list_command_invocations(CommandId=L_SSMCommandID,InstanceId=InstanceIDArray[0],Details=True)
        return 1
    else:
        return 0

def manageRetValue(retValue,FuncName,input, context):
    global responseStr
    if (retValue == 1):
        # responseStr['Status'][FuncName] = "Success"
        responseStr[FuncName] = "Success"

    else:
        # responseStr['Status'][FuncName] = "Failed"
        responseStr[FuncName] = "Failed"
        cfnresponse.send(input, context, cfnresponse.FAILED, {'Status':json.dumps(responseStr)})
        sys.exit(0)

def getNetworkInterfaceId(EC2InstanceId):
    session = boto3.Session()
    ec2Client = session.client('ec2')
    response = ec2Client.describe_instances(InstanceIds=[EC2InstanceId])
    ENIId = jmespath.search("Reservations[].Instances[].NetworkInterfaces[].NetworkInterfaceId", response)
    ENIId_str = ''.join(ENIId)
    return ENIId_str
    
def setSecondaryInterfaceIP(EC2InstanceENIId):
    session = boto3.Session()
    ec2Client = session.client('ec2')
    response = ec2Client.assign_private_ip_addresses(NetworkInterfaceId=EC2InstanceENIId,SecondaryPrivateIpAddressCount=1)
    assignedIPv4 = jmespath.search("AssignedPrivateIpAddresses[].PrivateIpAddress", response)
    assignedIPv4_str = ''.join(assignedIPv4)
    return assignedIPv4_str
    
def updateClusterPackages(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion):
    CommandArray = []
    CommandArray.append('zypper update -y SAPHanaSR pacemaker* resource-agents cluster-glue aws-vpc-move-ip corosync crmsh hawk2')
    CommentStr = 'Update cluster packages on Primary'
    InstanceIDArray =[HANAPrimaryInstanceID]
    if ( executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion) == 1 ):
        CommentStr = 'Update cluster packages on Secondary'
        InstanceIDArray =[HANASecondaryInstanceID]
        return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)
    else:
        return 0

def lambda_handler(input, context):
    global responseStr
    try:
        if (input['RequestType'] == "Update") or (input['RequestType'] == "Create"):
            HANAPrimaryInstanceID = input['ResourceProperties']['PrimaryInstanceId']
            HANASecondaryInstanceID = input['ResourceProperties']['SecondaryInstanceId']
            AWSRegion = input['ResourceProperties']['AWSRegion']
            HANAPrimaryIPAddress = input['ResourceProperties']['HANAPrimaryIPAddress']
            HANASecondaryIPAddress = input['ResourceProperties']['HANASecondaryIPAddress']
            hanaSID = input['ResourceProperties']['SID']
            hanaInstanceNo = input['ResourceProperties']['InstanceNo']
            HANAMasterPass = input['ResourceProperties']['HANAMasterPass']
            MyOS = input['ResourceProperties']['MyOS']

            if 'SUSE' in MyOS.upper():
                # Update cluster packages
                retValue = updateClusterPackages(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion)
                manageRetValue(retValue,"updateClusterPackages",input, context)
                
                # Retrieve ENI IDs from both HANA instances
                HANAPrimaryENIID = getNetworkInterfaceId(HANAPrimaryInstanceID)
                HANASecondaryENIID = getNetworkInterfaceId(HANASecondaryInstanceID)
            
                # Assign a Second IP to both HANA instances
                HANAPrimarySecondIP = setSecondaryInterfaceIP(HANAPrimaryENIID)
                responseStr['HANAPrimarySecondIP'] = HANAPrimarySecondIP
                HANASecondarySecondIP = setSecondaryInterfaceIP(HANASecondaryENIID)
                responseStr['HANASecondarySecondIP'] = HANASecondarySecondIP
                    
                retValue = updateNetworkConfig(HANAPrimaryInstanceID,HANAPrimaryIPAddress,HANAPrimarySecondIP,AWSRegion)
                manageRetValue(retValue,"updateNetworkConfigPrimary",input, context)

                retValue = updateNetworkConfig(HANASecondaryInstanceID,HANASecondaryIPAddress,HANASecondarySecondIP,AWSRegion)
                manageRetValue(retValue,"updateNetworkConfigSecondary",input, context)
            else:
                responseStr['HANAPrimarySecondIP'] = 'NotSet'
                responseStr['HANASecondarySecondIP'] = 'NotSet'
                responseStr['updateNetworkConfigPrimary'] = 'NotSet'
                responseStr['updateNetworkConfigSecondary'] = 'NotSet'
                
            retValue = backupHANAonPrimary(HANAPrimaryInstanceID,hanaSID,hanaInstanceNo,HANAMasterPass,AWSRegion)
            manageRetValue(retValue,"backupHANAonPrimary",input, context)
            
            cfnresponse.send(input, context, cfnresponse.SUCCESS, responseStr)
        else:
            responseStr['Status'] = 'Nothing to do as Request Type is : ' + input['RequestType']
            cfnresponse.send(input, context, cfnresponse.SUCCESS, responseStr)
    except Exception as e:
        responseStr['Status'] = str(e)
        cfnresponse.send(input, context, cfnresponse.FAILED, responseStr)