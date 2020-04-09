import cfnresponse
import json
import boto3
import time
import sys

responseStr = {'Status' : {}}

def getRouteTableID(PrimarySubnetId,SecondarySubnetId,vpcId,AWSRegion):

    session = boto3.Session()
    ec2 = session.client('ec2', region_name=AWSRegion)
    response = ec2.describe_route_tables(
                    Filters=[{'Name': 'association.subnet-id','Values': [PrimarySubnetId]}]
                )
    if len(response['RouteTables']) == 0:
        response = ec2.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpcId]},{'Name': 'association.main', 'Values': ['true',]}])

    PrimaryRouteTableID=response['RouteTables'][0]['Associations'][0]['RouteTableId']
    
    response = ec2.describe_route_tables(
                    Filters=[{'Name': 'association.subnet-id','Values': [SecondarySubnetId]}]
                )
    if len(response['RouteTables']) == 0:
        response = ec2.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpcId]},{'Name': 'association.main', 'Values': ['true',]}])
        
    SecondaryRouteTableID=response['RouteTables'][0]['Associations'][0]['RouteTableId']

    if PrimaryRouteTableID == SecondaryRouteTableID :
            return PrimaryRouteTableID
    else:
            return 0

def updateRouteTable(HANAPrimaryInstanceID,HANAVirtualIP,RTabId,AWSRegion):
    session = boto3.Session()
    ec2 = session.client('ec2', region_name=AWSRegion)
    response=ec2.create_route(
        RouteTableId=RTabId,
        DestinationCidrBlock=HANAVirtualIP+'/32',
        InstanceId=HANAPrimaryInstanceID
    )
    return 1

def deleteVirtualIPRoute(HANAVirtualIP,RTabId,AWSRegion):
    session = boto3.Session()
    ec2 = session.client('ec2', region_name=AWSRegion)
    response=ec2.delete_route(
        DestinationCidrBlock=HANAVirtualIP+'/32',
        RouteTableId=RTabId
    )

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

def setupAWSConfigProfile(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion):
    CommandArray = []
    CommandArray.append('mkdir /root/.aws')
    CommandArray.append('echo "[default]" > /root/.aws/config')
    CommandArray.append('echo "region = '+AWSRegion+'" >> /root/.aws/config')
    CommandArray.append('echo "[profile cluster]" >> /root/.aws/config')
    CommandArray.append('echo "region = '+AWSRegion+'" >> /root/.aws/config')
    CommandArray.append('echo "output = text" >> /root/.aws/config')
    CommandArray.append('chmod 600 /root/.aws/config')
    CommentStr = 'AWS cofig file on Primary & Secondary'
    InstanceIDArray =[HANAPrimaryInstanceID,HANASecondaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def disableSourceDestinationCheck(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion):
    session = boto3.Session()
    ec2 = session.client('ec2', region_name=AWSRegion)
    ec2.modify_instance_attribute(SourceDestCheck={'Value': False}, InstanceId=HANAPrimaryInstanceID)
    ec2.modify_instance_attribute(SourceDestCheck={'Value': False}, InstanceId=HANASecondaryInstanceID)
    return verifySourceDestinationCheck(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion)

def verifySourceDestinationCheck(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion):
    session = boto3.Session()
    ec2 = session.client('ec2', region_name=AWSRegion)
    retPri=ec2.describe_instance_attribute(Attribute='sourceDestCheck', InstanceId=HANAPrimaryInstanceID)
    if (retPri['SourceDestCheck']['Value'] == False):
        retSec=ec2.describe_instance_attribute(Attribute='sourceDestCheck', InstanceId=HANASecondaryInstanceID)
        if (retSec['SourceDestCheck']['Value'] == False):
            return 1
        else:
            return 0
    else:
        return 0

def createPacemakerTag(HANAPrimaryInstanceID,HANASecondaryInstanceID,PaceMakerTag,HANAPrimaryHostname,HANASecondaryHostname,hanaSID,AWSRegion):
    session = boto3.Session()
    ec2 = session.client('ec2', region_name=AWSRegion)
    ec2.create_tags(Resources=[HANAPrimaryInstanceID],Tags=[{'Key': PaceMakerTag,'Value': HANAPrimaryHostname}])
    ec2.create_tags(Resources=[HANAPrimaryInstanceID],Tags=[{'Key': 'Name','Value': 'HANA - ' + hanaSID +' - Primary'}])
    ec2.create_tags(Resources=[HANASecondaryInstanceID],Tags=[{'Key': PaceMakerTag,'Value': HANASecondaryHostname}])
    ec2.create_tags(Resources=[HANASecondaryInstanceID],Tags=[{'Key': 'Name','Value': 'HANA - ' + hanaSID +' - Secondary'}])
    return verifyPackemakerTag(HANAPrimaryInstanceID,HANASecondaryInstanceID,PaceMakerTag,HANAPrimaryHostname,HANASecondaryHostname,hanaSID,AWSRegion)

def verifyPackemakerTag(HANAPrimaryInstanceID,HANASecondaryInstanceID,PaceMakerTag,HANAPrimaryHostname,HANASecondaryHostname,hanaSID,AWSRegion):
    session = boto3.Session()
    ec2 = session.client('ec2', region_name=AWSRegion)
    instDetail = ec2.describe_tags(Filters=[{'Name': 'tag:'+PaceMakerTag,'Values': [HANAPrimaryHostname,HANASecondaryHostname]}])
    count = 0
    for idx, tag in enumerate(instDetail['Tags']):
        if (tag['ResourceId'] ==  HANAPrimaryInstanceID or tag['ResourceId'] ==  HANASecondaryInstanceID):
            count = count + 1
    if (count == 2):
        return 1
    else:
        return 0

def installRsyslog(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion):
    CommandArray = []
    # SLES12 SP4 & SLES 15 do not have aws-vpc-move-ip installed by default
    CommandArray.append('zypper install -y aws-vpc-move-ip')
    CommandArray.append('zypper install -y rsyslog')
    CommentStr = 'Install rsyslog'
    InstanceIDArray =[HANAPrimaryInstanceID,HANASecondaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def copySSFSFilesFromPrimaryToS3(HANAPrimaryInstanceID,TempS3Bucket,hanaSID,AWSRegion):
    CommandArray = []
    CommandArray.append('aws s3 cp /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/data/SSFS_'+hanaSID+'.DAT '+TempS3Bucket)
    CommandArray.append('aws s3 cp /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/key/SSFS_'+hanaSID+'.KEY '+TempS3Bucket)
    CommentStr = 'Copy SSFS from Primary to TempBucket'
    InstanceIDArray =[HANAPrimaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def copySSFSFilesFromS3ToSecondary(HANASecondaryInstanceID,TempS3Bucket,hanaSID,AWSRegion):
    CommandArray = []
    CommandArray.append('su - '+hanaSID.lower()+'adm -c "HDB stop"')
    CommandArray.append('mv /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/data/SSFS_'+hanaSID+'.DAT /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/data/SSFS_'+hanaSID+'.DAT.BAK')
    CommandArray.append('mv /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/key/SSFS_'+hanaSID+'.KEY /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/key/SSFS_'+hanaSID+'.KEY.BAK')
    CommandArray.append('aws s3 cp '+TempS3Bucket+'SSFS_'+hanaSID+'.DAT /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/data/SSFS_'+hanaSID+'.DAT')
    CommandArray.append('aws s3 cp '+TempS3Bucket+'SSFS_'+hanaSID+'.KEY /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/key/SSFS_'+hanaSID+'.KEY')
    CommandArray.append('chown '+hanaSID.lower()+'adm:sapsys /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/data/SSFS_'+hanaSID+'.DAT')
    CommandArray.append('chown '+hanaSID.lower()+'adm:sapsys /usr/sap/'+hanaSID+'/SYS/global/security/rsecssfs/key/SSFS_'+hanaSID+'.KEY')
    CommentStr = 'Copy SSFS from TempBucket to Secondary'
    InstanceIDArray =[HANASecondaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def disableHANAAutoStartSecondary(HANASecondaryInstanceID,HANASecondaryHostname,hanaSID,hanaInstanceNo,AWSRegion):
    CommandArray = []
    CommandArray.append("sed -i 's,^\(Autostart[ ]*=\).*,\1'Autostart=0',g' /usr/sap/"+hanaSID.upper()+"/SYS/profile/"+hanaSID.upper()+"_HDB"+hanaInstanceNo+"_"+HANASecondaryHostname)
    CommentStr = 'Disable HANA AutoStart on Secondary'
    InstanceIDArray =[HANASecondaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def disableHANAAutoStartPrimary(HANAPrimaryInstanceID,HANAPrimaryHostname,hanaSID,hanaInstanceNo,AWSRegion):
    CommandArray = []
    CommandArray.append("sed -i 's,^\(Autostart[ ]*=\).*,\1'Autostart=0',g' /usr/sap/"+hanaSID.upper()+"/SYS/profile/"+hanaSID.upper()+"_HDB"+hanaInstanceNo+"_"+HANAPrimaryHostname)
    CommentStr = 'Disable HANA AutoStart on Primary'
    InstanceIDArray =[HANAPrimaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def updateHostFileSecondary(HANASecondaryInstanceID,HANAPrimaryHostname,HANAPrimaryIPAddress,domainName,AWSRegion):
    CommandArray = []
    CommandArray.append('echo "'+HANAPrimaryIPAddress+'   '+HANAPrimaryHostname+'.'+domainName+'   '+HANAPrimaryHostname+'" >> /etc/hosts')
    CommentStr = 'Update Host File on Secondary'
    InstanceIDArray =[HANASecondaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def updateHostFilePrimary(HANAPrimaryInstanceID,HANASecondaryHostname,HANASecondaryIPAddress,domainName,AWSRegion):
    CommandArray = []
    CommandArray.append('echo "'+HANASecondaryIPAddress+'   '+HANASecondaryHostname+'.'+domainName+'   '+HANASecondaryHostname+'" >> /etc/hosts')
    CommentStr = 'Update Host File on Primary'
    InstanceIDArray =[HANAPrimaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def updatePreserveHostName(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion):
    CommandArray = []
    CommandArray.append("sed -i 's,^\(preserve_hostname[ ]*:\).*,\1'preserve_hostname:\ true',g' /etc/cloud/cloud.cfg")
    CommentStr = 'Update Preserve Hostname in cloud.cfg on Primary & Secondary'
    InstanceIDArray =[HANAPrimaryInstanceID,HANASecondaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def updateDefaultTasksMax(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion):
    #https://www.novell.com/support/kb/doc.php?id=7018594
    CommandArray = []
    CommandArray.append('sed -i".bak" "/\bDefaultTasksMax\b/d" /etc/systemd/system.conf')
    CommandArray.append('echo -e "DefaultTasksMax=8192">> /etc/systemd/system.conf')
    CommandArray.append('systemctl daemon-reload')
    CommentStr = 'Update DefaultTasksMax on Primary & Secondary'
    InstanceIDArray =[HANAPrimaryInstanceID,HANASecondaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def CompleteCoroSyncSetup(HANAPrimaryInstanceID,RTabId,HANAVirtualIP,hanaSID,hanaInstanceNo,PaceMakerTag,AWSRegion):
    CommandArray = []
    CommandArray.append('mkdir /root/ClusterSetup')
    CommandArray.append('echo "primitive res_AWS_STONITH stonith:external/ec2 \\\\" > /root/ClusterSetup/aws-stonith.txt')
    CommandArray.append('echo "op start interval=0 timeout=180 \\\\" >> /root/ClusterSetup/aws-stonith.txt')
    CommandArray.append('echo "op stop interval=0 timeout=180 \\\\" >> /root/ClusterSetup/aws-stonith.txt')
    CommandArray.append('echo "op monitor interval=120 timeout=60 \\\\" >> /root/ClusterSetup/aws-stonith.txt')
    CommandArray.append('echo "meta target-role=Started \\\\" >> /root/ClusterSetup/aws-stonith.txt')
    CommandArray.append('echo "params tag='+PaceMakerTag+' profile=cluster" >> /root/ClusterSetup/aws-stonith.txt')
    CommandArray.append('crm configure load update /root/ClusterSetup/aws-stonith.txt')

    CommandArray.append('echo "primitive res_AWS_IP ocf:suse:aws-vpc-move-ip \\\\" > /root/ClusterSetup/aws-ip-move.txt')
    #changed address to ip as address has been deprecated in lastest version (also added zypper install aws-vpc-move-ip so that latest version of agents is installed)
    CommandArray.append('echo "params ip='+HANAVirtualIP+' routing_table='+RTabId+' interface=eth0 profile=cluster \\\\" >> /root/ClusterSetup/aws-ip-move.txt')
    CommandArray.append('echo "op start interval=0 timeout=180 \\\\" >> /root/ClusterSetup/aws-ip-move.txt')
    CommandArray.append('echo "op stop interval=0 timeout=180 \\\\" >> /root/ClusterSetup/aws-ip-move.txt')
    CommandArray.append('echo "op monitor interval=60 timeout=60 \\\\" >> /root/ClusterSetup/aws-ip-move.txt')
    CommandArray.append('echo "meta target-role=Started" >> /root/ClusterSetup/aws-ip-move.txt')
    CommandArray.append('crm configure load update /root/ClusterSetup/aws-ip-move.txt')

    CommandArray.append('echo "property \$id=cib-bootstrap-options \\\\" > /root/ClusterSetup/crm-bs.txt')
    CommandArray.append('echo "              stonith-enabled=true \\\\" >> /root/ClusterSetup/crm-bs.txt')
    #Changed poweroff to off as poweroff has been deprecated
    CommandArray.append('echo "              stonith-action=off \\\\" >> /root/ClusterSetup/crm-bs.txt')
    CommandArray.append('echo "stonith-timeout=150s" >> /root/ClusterSetup/crm-bs.txt')
    CommandArray.append('echo "rsc_defaults \$id=rsc-options \\\\" >> /root/ClusterSetup/crm-bs.txt')
    CommandArray.append('echo "resource-stickiness=1000 \\\\" >> /root/ClusterSetup/crm-bs.txt')
    CommandArray.append('echo "migration-threshold=5000" >> /root/ClusterSetup/crm-bs.txt')
    CommandArray.append('echo "op_defaults \$id=op-options \\\\" >> /root/ClusterSetup/crm-bs.txt')
    CommandArray.append('echo "timeout=600" >> /root/ClusterSetup/crm-bs.txt')
    CommandArray.append('crm configure load update /root/ClusterSetup/crm-bs.txt')

    CommandArray.append('echo "primitive rsc_SAPHanaTopology_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+' ocf:suse:SAPHanaTopology \\\\" > /root/ClusterSetup/crm-hana-topology.txt')
    CommandArray.append('echo "operations \$id=rsc_sap2_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+'-operations \\\\" >> /root/ClusterSetup/crm-hana-topology.txt')
    CommandArray.append('echo "op monitor interval=10 timeout=300 \\\\" >> /root/ClusterSetup/crm-hana-topology.txt')
    CommandArray.append('echo "op start interval=0 timeout=300 \\\\" >> /root/ClusterSetup/crm-hana-topology.txt')
    CommandArray.append('echo "op stop interval=0 timeout=300 \\\\" >> /root/ClusterSetup/crm-hana-topology.txt')
    CommandArray.append('echo "params SID='+hanaSID.upper()+' InstanceNumber='+hanaInstanceNo+'" >> /root/ClusterSetup/crm-hana-topology.txt')
    CommandArray.append('echo "clone cln_SAPHanaTopology_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+' rsc_SAPHanaTopology_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+' \\\\" >> /root/ClusterSetup/crm-hana-topology.txt')
    CommandArray.append('echo "meta clone-node-max=1 interleave=true" >> /root/ClusterSetup/crm-hana-topology.txt')
    CommandArray.append('crm configure load update /root/ClusterSetup/crm-hana-topology.txt')


    CommandArray.append('echo "primitive rsc_SAPHana_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+' ocf:suse:SAPHana \\\\" > /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "operations \$id=rsc_sap_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+'-operations \\\\" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "op start interval=0 timeout=3600 \\\\" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "op stop interval=0 timeout=3600 \\\\" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "op promote interval=0 timeout=3600 \\\\" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "op monitor interval=60 role=Master timeout=700 \\\\" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "op monitor interval=61 role=Slave timeout=700 \\\\" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "params SID='+hanaSID.upper()+' InstanceNumber='+hanaInstanceNo+' PREFER_SITE_TAKEOVER=true \\\\" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "DUPLICATE_PRIMARY_TIMEOUT=7200 AUTOMATED_REGISTER=true" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "ms msl_SAPHana_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+' rsc_SAPHana_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+' \\\\" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('echo "meta clone-max=2 clone-node-max=1 interleave=true" >> /root/ClusterSetup/crm-saphana.txt')
    CommandArray.append('crm configure load update /root/ClusterSetup/crm-saphana.txt')

    CommandArray.append('echo "colocation col_IP_Primary 2000: res_AWS_IP:Started msl_SAPHana_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+':Master" > /root/ClusterSetup/aws-constraint.txt')
    CommandArray.append('echo "order ord_SAPHana 2000: cln_SAPHanaTopology_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+' msl_SAPHana_'+hanaSID.upper()+'_HDB'+hanaInstanceNo+'" >> /root/ClusterSetup/aws-constraint.txt')
    CommandArray.append('crm configure load update /root/ClusterSetup/aws-constraint.txt')

    CommentStr = 'corosycn setup for SAP HANA'
    InstanceIDArray =[HANAPrimaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def StartPaceMaker(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAMasterPass,AWSRegion):
    CommandArray=[]
    CommandArray.append('systemctl start pacemaker')
    CommandArray.append('chkconfig pacemaker on')
    CommandArray.append('systemctl start hawk')
    CommandArray.append('chkconfig hawk on')
    CommandArray.append('echo "hacluster:'+HANAMasterPass+'" | chpasswd')
    CommentStr = 'Start Pacemaker on Primary and configure for autostart with OS'
    InstanceIDArray =[HANAPrimaryInstanceID]
    if ( executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion) == 1 ):
        CommentStr = 'Start Pacemaker on Secondary and configure for autostart with OS'
        InstanceIDArray =[HANASecondaryInstanceID]
        return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)
    else:
        return 0

def createCoroSyncConfig(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANASecondaryIPAddress,HANAPrimaryIPAddress,HANAPrimaryCorosync2ndIP,HANASecondaryCorosync2ndIP,AWSRegion):
    CommandArray = []
    CommandArray.append('echo "# Please read the corosync.conf.5 manual page" > /etc/corosync/corosync.conf')
    CommandArray.append('echo "totem {" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        version: 2" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        token: 30000" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        consensus: 36000" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        token_retransmits_before_loss_const: 6" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        crypto_cipher: none" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        crypto_hash: none" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        clear_node_high_bit: yes" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        rrp_mode: passive" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo " " >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        interface {" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                ringnumber: 0" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                bindnetaddr: '+HANAPrimaryIPAddress+'" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                mcastport: 5405" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                ttl: 1" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        }" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        transport: udpu" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "}" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "logging {" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        fileline: off" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        to_logfile: yes" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        to_syslog: yes" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        logfile: /var/log/cluster/corosync.log" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        debug: off" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        timestamp: on" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        logger_subsys {" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                subsys: QUORUM" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                debug: off" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        }" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "}" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "nodelist {" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        node {" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                ring0_addr: '+HANAPrimaryIPAddress+'" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                ring1_addr: '+HANAPrimaryCorosync2ndIP+'" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                nodeid: 1" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        }" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        node {" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                ring0_addr: '+HANASecondaryIPAddress+'" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                ring1_addr: '+HANASecondaryCorosync2ndIP+'" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "                nodeid: 2" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        }" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "}" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo " " >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        quorum {" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        # Enable and configure quorum subsystem (default: off)" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        # see also corosync.conf.5 and votequorum.5" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        provider: corosync_votequorum" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        expected_votes: 2" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "        two_node: 1" >> /etc/corosync/corosync.conf')
    CommandArray.append('echo "}" >> /etc/corosync/corosync.conf')
    CommandArray.append('chown root:root /etc/corosync/corosync.conf')
    CommandArray.append('chmod 400 /etc/corosync/corosync.conf')
    CommentStr = 'CoroSync cofigfile on Primary'
    InstanceIDArray =[HANAPrimaryInstanceID]
    if ( executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion) == 1 ):
        CommandArray[13]=None
        CommandArray[13]='echo "                bindnetaddr: '+HANASecondaryIPAddress+'" >> /etc/corosync/corosync.conf'
        CommentStr = 'CoroSync cofigfile on Secondary'
        InstanceIDArray =[HANASecondaryInstanceID]
        return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)
    else:
        return 0

def setupCoroSyncKeyPrimary(HANAPrimaryInstanceID,HANASecondaryInstanceID,TempS3Bucket,AWSRegion):
    CommandArray = []
    CommandArray.append('corosync-keygen')
    CommandArray.append('aws s3 cp /etc/corosync/authkey '+TempS3Bucket+'authkey')
    CommentStr = 'CoroSync Key Generate On Primary'
    InstanceIDArray =[HANAPrimaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def copyCoroSyncKeyToSecondary(HANAPrimaryInstanceID,HANASecondaryInstanceID,TempS3Bucket,AWSRegion):
    CommandArray = []
    CommandArray.append('aws s3 cp '+TempS3Bucket+'authkey '+'/etc/corosync/authkey')
    CommandArray.append('chown root:root /etc/corosync/authkey')
    CommandArray.append('chmod 400 /etc/corosync/authkey')
    CommentStr = 'CoroSync Key Copy On Secondary'
    InstanceIDArray =[HANASecondaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def setupHSRPrimary(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAPrimarySite,HANASecondarySite,HANAPrimaryHostname,hanaSID,hanaInstanceNo,AWSRegion):
    CommandArray = []
    CommandArray.append('su - '+hanaSID.lower()+'adm -c "hdbnsutil -sr_enable --name='+HANAPrimarySite+'"')
    CommentStr = 'Enable HSR on Primary'
    InstanceIDArray =[HANAPrimaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def setupHSRSecondary(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAPrimarySite,HANASecondarySite,HANAPrimaryHostname,hanaSID,hanaInstanceNo,AWSRegion):
    CommandArray = []
    CommandArray.append('su - '+hanaSID.lower()+'adm -c "HDB stop"')
    CommandArray.append('su - '+hanaSID.lower()+'adm -c "hdbnsutil -sr_register --name='+HANASecondarySite+' --remoteHost='+HANAPrimaryHostname+' --remoteInstance='+hanaInstanceNo+'  --replicationMode=sync --operationMode=logreplay"')
    CommentStr = 'Enable HSR on Secondary'
    InstanceIDArray =[HANASecondaryInstanceID]
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def manageRetValue(retValue,FuncName,input, context):
    global responseStr
    if (retValue == 1):
        responseStr['Status'][FuncName] = "Success"
    else:
        responseStr['Status'][FuncName] = "Failed"
        cfnresponse.send(input, context, cfnresponse.FAILED, {'Status':json.dumps(responseStr)})
        sys.exit(0)

def setupSUSESAPHanaHook(HANAPrimaryInstanceID,HANASecondaryInstanceID,hanaSID,sidadm,AWSRegion):
    CommandArray = []
    CommandArray.append('echo " " >> /hana/shared/'+hanaSID.upper()+'/global/hdb/custom/config/global.ini')
    CommandArray.append('echo "[ha_dr_provider_SAPHanaSR]" >> /hana/shared/'+hanaSID.upper()+'/global/hdb/custom/config/global.ini')
    CommandArray.append('echo "provider = SAPHanaSR" >> /hana/shared/'+hanaSID.upper()+'/global/hdb/custom/config/global.ini')
    CommandArray.append('echo "path = /usr/share/SAPHanaSR" >> /hana/shared/'+hanaSID.upper()+'/global/hdb/custom/config/global.ini')
    CommandArray.append('echo "execution_order = 1" >> /hana/shared/'+hanaSID.upper()+'/global/hdb/custom/config/global.ini')
    CommandArray.append('echo " " >> /hana/shared/'+hanaSID.upper()+'/global/hdb/custom/config/global.ini')
    CommandArray.append('echo "[trace]" >> /hana/shared/'+hanaSID.upper()+'/global/hdb/custom/config/global.ini')
    CommandArray.append('echo "ha_dr_saphanasr = info" >> /hana/shared/'+hanaSID.upper()+'/global/hdb/custom/config/global.ini')
    CommandArray.append('echo "'+sidadm+' ALL=(ALL) NOPASSWD: /usr/sbin/crm_attribute -n hana_'+hanaSID.lower()+'_site_srHook_*" >> /etc/sudoers')
    CommentStr = 'Enable SAP HANA Hook'
    InstanceIDArray =[HANAPrimaryInstanceID]
    if ( executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion) == 1 ):
        InstanceIDArray =[HANASecondaryInstanceID]
        return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)
    else:
        return 0

def RHELStartPCSService(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAMasterPass,AWSRegion):
    CommandArray = []
    CommandArray.append('[ ! -e /usr/bin/aws ] && ln -s /usr/local/bin/aws /usr/bin/aws')
    CommandArray.append('yum install -y pcs pacemaker fence-agents-aws aws-vpc-move-ip')
    CommandArray.append('yum install -y resource-agents-sap-hana resource-agents')
    CommandArray.append('mkdir -p /var/log/pcsd')
    CommandArray.append('mkdir -p /var/log/cluster')
    CommandArray.append('mkdir -p /var/log/sa')
    CommandArray.append('systemctl start pcsd.service')
    CommandArray.append('systemctl enable pcsd.service')
    CommandArray.append('echo "hacluster:'+HANAMasterPass+'" | chpasswd')
    InstanceIDArray =[HANAPrimaryInstanceID,HANASecondaryInstanceID]
    CommentStr = 'Setup user hacluster and PCSD Service'
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def RHELSetupHANACluster(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAPrimaryHostname,HANASecondaryHostname,HANAMasterPass,AWSRegion,hanaSID,hanaInstanceNo,HANAVirtualIP,RTabId):
    CommandArray = []
    CommandArray.append('pcs cluster auth '+HANAPrimaryHostname+' '+HANASecondaryHostname+' -u hacluster -p '+HANAMasterPass)
    CommandArray.append('pcs cluster setup --name hanacluster  '+HANAPrimaryHostname+' '+HANASecondaryHostname)
    CommandArray.append('pcs cluster enable --all')
    CommandArray.append('pcs cluster start --all')
    CommandArray.append('pcs stonith create clusterfence fence_aws region='+AWSRegion+' pcmk_host_map="'+HANAPrimaryHostname+':'+HANAPrimaryInstanceID+';'+HANASecondaryHostname+':'+HANASecondaryInstanceID+'" power_timeout=240 pcmk_reboot_timeout=480 pcmk_reboot_retries=4')
    #Removed resource-stickiness & migration-threshold based on recommendations from Red Hat
    #CommandArray.append('pcs resource defaults resource-stickiness=1000')
    #CommandArray.append('pcs resource defaults migration-threshold=5000')
    CommandArray.append('pcs resource create SAPHanaTopology_'+hanaSID+'_'+hanaInstanceNo+' SAPHanaTopology SID='+hanaSID+' InstanceNumber='+hanaInstanceNo+' op start timeout=600 op stop timeout=300 op monitor interval=10 timeout=600 --clone clone-max=2 clone-node-max=1 interleave=true')
    CommandArray.append('pcs resource create SAPHana_'+hanaSID+'_'+hanaInstanceNo+' SAPHana SID='+hanaSID+' InstanceNumber='+hanaInstanceNo+' PREFER_SITE_TAKEOVER=true DUPLICATE_PRIMARY_TIMEOUT=7200 AUTOMATED_REGISTER=true op start timeout=3600 op stop timeout=3600 op monitor interval=61 role="Slave" timeout=700 op monitor interval=59 role="Master" timeout=700 op promote timeout=3600 op demote timeout=3600 master meta notify=true clone-max=2 clone-node-max=1 interleave=true')
    CommandArray.append('pcs resource create SAPHana_'+hanaSID+'_OIP aws-vpc-move-ip ip='+HANAVirtualIP+' interface=eth0 routing_table='+RTabId)
    CommandArray.append('pcs constraint order SAPHanaTopology_'+hanaSID+'_'+hanaInstanceNo+'-clone then SAPHana_'+hanaSID+'_'+hanaInstanceNo+'-master symmetrical=false')
    CommandArray.append('pcs constraint colocation add SAPHana_'+hanaSID+'_OIP with master SAPHana_'+hanaSID+'_'+hanaInstanceNo+'-master 2000')
    InstanceIDArray =[HANAPrimaryInstanceID]
    CommentStr = 'Setup HANA Cluster Config'
    return executeSSMCommands(CommandArray,InstanceIDArray,CommentStr,AWSRegion)

def lambda_handler(input, context):
    global responseStr
    try:
        if (input['RequestType'] == "Update") or (input['RequestType'] == "Create"):
            HANAPrimaryInstanceID = input['ResourceProperties']['PrimaryInstanceId']
            HANASecondaryInstanceID = input['ResourceProperties']['SecondaryInstanceId']
            HANAPrimaryHostname = input['ResourceProperties']['PrimaryHostName']
            HANASecondaryHostname = input['ResourceProperties']['SecondaryHostName']
            PaceMakerTag = input['ResourceProperties']['PaceMakerTag']
            AWSRegion = input['ResourceProperties']['AWSRegion']
            HANAVirtualIP = input['ResourceProperties']['VirtualIP']
            PrimarySubnetId = input['ResourceProperties']['PrimarySubnetId']
            SecondarySubnetId = input['ResourceProperties']['SecondarySubnetId']
            hanaSID = input['ResourceProperties']['SID']
            hanaInstanceNo = input['ResourceProperties']['InstanceNo']
            HANAMasterPass = input['ResourceProperties']['HANAMasterPass']
            TempS3Bucket = input['ResourceProperties']['TempS3Bucket']
            HANAPrimaryIPAddress = input['ResourceProperties']['HANAPrimaryIPAddress']
            HANASecondaryIPAddress = input['ResourceProperties']['HANASecondaryIPAddress']
            domainName = input['ResourceProperties']['domainName']
            HANAPrimarySite = input['ResourceProperties']['PrimaryHANASite']
            HANASecondarySite = input['ResourceProperties']['SecondaryHANASite']
            VPCID=input['ResourceProperties']['VPCID']
            MyOS = input['ResourceProperties']['MyOS']
            MyOS = MyOS.upper()
            HANAPrimaryCorosync2ndIP = input['ResourceProperties']['HANAPrimaryCorosync2ndIP']
            HANASecondaryCorosync2ndIP = input['ResourceProperties']['HANASecondaryCorosync2ndIP']
            sidadm = hanaSID.lower()+"adm"

            retValue = setupAWSConfigProfile(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion)
            manageRetValue(retValue,"setupAWSConfigProfile",input, context)

            retValue = createPacemakerTag(HANAPrimaryInstanceID,HANASecondaryInstanceID,PaceMakerTag,HANAPrimaryHostname,HANASecondaryHostname,hanaSID,AWSRegion)
            manageRetValue(retValue,"createPacemakerTag",input, context)

            retValue = disableSourceDestinationCheck(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion)
            manageRetValue(retValue,"disableSourceDestinationCheck",input, context)
            
            RTabId = getRouteTableID(PrimarySubnetId,SecondarySubnetId,VPCID,AWSRegion)
            updateRouteTable(HANAPrimaryInstanceID,HANAVirtualIP,RTabId,AWSRegion)
            manageRetValue(retValue,"getRouteTableID",input, context)

            if 'SUSE' in MyOS :
                 retValue = installRsyslog(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion)
                 responseStr["Status"]["installRsyslog"] = "Success"

            retValue = copySSFSFilesFromPrimaryToS3(HANAPrimaryInstanceID,TempS3Bucket,hanaSID,AWSRegion)
            manageRetValue(retValue,"copySSFSFilesFromPrimaryToS3",input, context)

            retValue = copySSFSFilesFromS3ToSecondary(HANASecondaryInstanceID,TempS3Bucket,hanaSID,AWSRegion)
            manageRetValue(retValue,"copySSFSFilesFromS3ToSecondary",input, context)

            retValue = disableHANAAutoStartSecondary(HANASecondaryInstanceID,HANASecondaryHostname,hanaSID,hanaInstanceNo,AWSRegion)
            manageRetValue(retValue,"disableHANAAutoStartSecondary",input, context)

            retValue = disableHANAAutoStartPrimary(HANAPrimaryInstanceID,HANAPrimaryHostname,hanaSID,hanaInstanceNo,AWSRegion)
            manageRetValue(retValue,"disableHANAAutoStartPrimary",input, context)

            retValue = updateHostFileSecondary(HANASecondaryInstanceID,HANAPrimaryHostname,HANAPrimaryIPAddress,domainName,AWSRegion)
            manageRetValue(retValue,"updateHostFileSecondary",input, context)

            retValue = updateHostFilePrimary(HANAPrimaryInstanceID,HANASecondaryHostname,HANASecondaryIPAddress,domainName,AWSRegion)
            manageRetValue(retValue,"updateHostFilePrimary",input, context)

            retValue = updatePreserveHostName(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion)
            manageRetValue(retValue,"updatePreserveHostName",input, context)
            
            if 'SUSE' in MyOS :
                retValue = updateDefaultTasksMax(HANAPrimaryInstanceID,HANASecondaryInstanceID,AWSRegion)
                manageRetValue(retValue,"updateDefaultTasksMax",input, context)

            retValue = setupHSRPrimary(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAPrimarySite,HANASecondarySite,HANAPrimaryHostname,hanaSID,hanaInstanceNo,AWSRegion)
            manageRetValue(retValue,"setupHSRPrimary",input, context)

            retValue = setupHSRSecondary(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAPrimarySite,HANASecondarySite,HANAPrimaryHostname,hanaSID,hanaInstanceNo,AWSRegion)
            manageRetValue(retValue,"setupHSRSecondary",input, context)

            if 'SUSE' in MyOS :
                retValue = setupCoroSyncKeyPrimary(HANAPrimaryInstanceID,HANASecondaryInstanceID,TempS3Bucket,AWSRegion)
                manageRetValue(retValue,"setupCoroSyncKeyPrimary",input, context)

                retValue = copyCoroSyncKeyToSecondary(HANAPrimaryInstanceID,HANASecondaryInstanceID,TempS3Bucket,AWSRegion)
                manageRetValue(retValue,"copyCoroSyncKeyToSecondary",input, context)

                retValue = createCoroSyncConfig(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANASecondaryIPAddress,HANAPrimaryIPAddress,HANAPrimaryCorosync2ndIP,HANASecondaryCorosync2ndIP,AWSRegion)
                manageRetValue(retValue,"createCoroSyncConfig",input, context)
                
                retValue = setupSUSESAPHanaHook(HANAPrimaryInstanceID,HANASecondaryInstanceID,hanaSID,sidadm,AWSRegion)
                manageRetValue(retValue,"setupSUSESAPHanaHook",input, context)

                retValue = StartPaceMaker(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAMasterPass,AWSRegion)
                manageRetValue(retValue,"StartPaceMaker",input, context)

                retValue = CompleteCoroSyncSetup(HANAPrimaryInstanceID,RTabId,HANAVirtualIP,hanaSID,hanaInstanceNo,PaceMakerTag,AWSRegion)
                manageRetValue(retValue,"CompleteCoroSyncSetup",input, context)
            else:
                retValue = RHELStartPCSService(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAMasterPass,AWSRegion)
                manageRetValue(retValue,"CompletePCSDServiceRHEL",input, context)

                retValue = RHELSetupHANACluster(HANAPrimaryInstanceID,HANASecondaryInstanceID,HANAPrimaryHostname,HANASecondaryHostname,HANAMasterPass,AWSRegion,hanaSID,hanaInstanceNo,HANAVirtualIP,RTabId)
                manageRetValue(retValue,"HANAClusterConfigRHEL",input, context)

            cfnresponse.send(input, context, cfnresponse.SUCCESS, {'Status':json.dumps(responseStr)})
        elif (input['RequestType'] == "Delete"):
            AWSRegion = input['ResourceProperties']['AWSRegion']
            HANAVirtualIP = input['ResourceProperties']['VirtualIP']
            PrimarySubnetId = input['ResourceProperties']['PrimarySubnetId']
            SecondarySubnetId = input['ResourceProperties']['SecondarySubnetId']
            VPCID=input['ResourceProperties']['VPCID']
            RTabId = getRouteTableID(PrimarySubnetId,SecondarySubnetId,VPCID,AWSRegion)
            deleteVirtualIPRoute(HANAVirtualIP,RTabId,AWSRegion)
            responseStr['Status'] = 'Virtual IP ' + HANAVirtualIP +'Removed From Route Table :' + RTabId
            cfnresponse.send(input, context, cfnresponse.SUCCESS, {'Status':json.dumps(responseStr)})
        else:
            responseStr['Status'] = 'Nothing to do as Request Type is : ' + input['RequestType']
            cfnresponse.send(input, context, cfnresponse.SUCCESS, {'Status':json.dumps(responseStr)})
    except Exception as e:
        responseStr['Status'] = str(e)
        cfnresponse.send(input, context, cfnresponse.FAILED, {'Status':json.dumps(responseStr)})