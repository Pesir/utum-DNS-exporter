import signal
from time import sleep

from kubernetes import client, config
from google.cloud import dns
import logging
import os


def exitExporter(signum, frame):
    logging.info("Exit exporter")
    exit(0)


def main():
    config.load_incluster_config()
    dns_client = dns.Client.from_service_account_json('/etc/dns-k8s-watcher/credentials.json')

    logging.basicConfig(level=logging.INFO)

    nodePortServices = {}
    node_ips = []
    xorCheck = False

    zone_string = os.getenv('zone')
    sleep_time_string = os.getenv('sleep_time',"60")
    sleep_time = int(sleep_time_string)

    zone_string = "private-gcp"
    sleep_time = 1

    if zone_string is None:
        logging.error("need to have env <zone>")
        exit(-1)

    zone = dns_client.zone(zone_string)
    if not zone.exists():
        logging.error("zone -" + zone_string +"- does not exist")
        signal.signal(signal.SIGTERM, exitExporter)
    zone.reload()
    while True:
        sleep(sleep_time)
        #logging.info("Start check")
        xorCheck = not xorCheck
        v1 = client.CoreV1Api()
        ret = v1.list_service_for_all_namespaces()
        for i in ret.items:
            if i.spec.type == "NodePort" and not i.metadata.annotations is None \
                    and not i.metadata.annotations.get("utum.de/google-dns")  is None:
                dns_name = i.metadata.annotations.get("utum.de/google-dns")
                x = {"revision": i.metadata.resource_version,
                     "namespace": i.metadata.namespace,
                     "name": i.metadata.name,
                     "ports": i.spec.ports,
                     "changed": True,
                     "dns_name": dns_name,
                     "xor-check": xorCheck,
                     "single-ip": i.metadata.annotations.get("utum.de/single-ip","False").lower() == "true"}

                if i.metadata.name+i.metadata.namespace in nodePortServices:
                    x["changed"] = (i.metadata.resource_version !=
                                    nodePortServices[i.metadata.name+i.metadata.namespace]["revision"])
                if not dns_name.endswith(zone.dns_name):
                    x["dns_name"] = dns_name +"."+zone.dns_name
                elif not dns_name.endswith(zone.dns_name[:-1]):
                    x["dns_name"] = dns_name + "."
                nodePortServices[i.metadata.name+i.metadata.namespace] = x

        ret = v1.list_node()
        ips_changed = False
        new_ips = []
        for i in ret.items:
            for address in i.status.addresses:
                if address.type == 'InternalIP':
                    new_ips.append(address.address)
        new_ips.sort()

        if new_ips != node_ips:
            logging.info("New Node ips detected")
            logging.info("OLD: " + str(node_ips))
            logging.info("NEW: " + str(new_ips))
            ips_changed = True
            node_ips = new_ips
        a_rr_set = {}
        srv_rr_set = {}
        if len(nodePortServices)>0:
            rr_list = []
            try:
                rr_list = list(zone.list_resource_record_sets())
            except Exception as e:
                logging.error("Failed to get DNS records", exc_info=True)
            for rr_element in rr_list:
                #print( rr_element)
                if rr_element.record_type == "A":
                    a_rr_set[rr_element.name] = rr_element
                elif rr_element.record_type == "SRV":
                    srv_rr_set[rr_element.name] = rr_element


        for key,s_config in nodePortServices.items():
            changed = False
            changes = zone.changes()
            srv_new_rr_set = {}
            for port in s_config['ports']:
                srv_name = s_config['dns_name'] if port.name is None \
                                                else str(port.name)+"."+ s_config['dns_name']
                srv_new_rr_set[srv_name] = zone.resource_record_set(srv_name,'SRV',120,
                                                            ["1 20 "+str(port.node_port)+" "+s_config['dns_name']])
            a_record_set = None
            if s_config['single-ip']:
                a_record_set = zone.resource_record_set(s_config['dns_name'],'A',120,[(new_ips[0])])
            else:
                a_record_set = zone.resource_record_set(s_config['dns_name'],'A',120,new_ips)
            if s_config['xor-check'] != xorCheck:
                logging.info("delete a record:" + s_config['dns_name'])
                changes.delete_record_set(a_record_set)
                for srv_name, srv_record_set in srv_new_rr_set.items():
                    logging.info("delete srv record:" + srv_name)
                    changes.delete_record_set(srv_record_set)
                changed = True
            elif s_config["changed"] or ips_changed:
                old_a_record = a_rr_set.get(s_config["dns_name"])
                if not old_a_record is None:
                    logging.info("delete OLD A record: " + s_config['dns_name'])
                    changes.delete_record_set(old_a_record)
                for srv_name, srv_record_set in srv_new_rr_set.items():
                    old_srv_record = srv_rr_set.get(srv_name)
                    if s_config["changed"] and not old_srv_record is None:
                        logging.info("delete OLD SRV record: " + srv_name)
                        changes.delete_record_set(old_srv_record)

                changes.add_record_set(a_record_set)
                logging.info("Add A record: " + s_config["dns_name"])
                if s_config["changed"]:
                    for srv_name, srv_record_set in srv_new_rr_set.items():
                        changes.add_record_set(srv_record_set)
                        logging.info("Add SRV record: " + srv_name)
                changed = True
            if changed:
                try:
                    changes.create()
                except Exception as e:
                    logging.error("Failed to apply DNS changes", exc_info=True)


if __name__ == '__main__':
    main()