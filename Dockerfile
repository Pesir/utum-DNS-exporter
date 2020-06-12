FROM python:3

RUN pip3 install google-cloud-dns kubernetes

ADD ./dns-k8s-watcher.py /

CMD [ "python3", "./dns-k8s-watcher.py"]
