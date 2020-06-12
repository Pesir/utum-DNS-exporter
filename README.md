# dns-k8s-watcher

Simple service to watch all Nodeport services and adds selected nodeports to the supplied gcp cloud dns zone.


required envs

zone  -  the zone where the entries should be added this is not the DNS name but the zone name.

optional envs

sleep_time - how long to wait until another check is performed.



requiered secret

requires a service account under the path /etc/dns-k8s-watcher/credentials.json