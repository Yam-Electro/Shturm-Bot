

http://172.16.50.130:8888/
пароль: ai1234

/opt/jupyter/worK - папка расшаренная с контейнером как /work/ - вне этой папки данные будут пропадать при рестарте


Если надо кастомизировать пакеты внутри Юпитера - меняй requirements.txt и запускай
```sh
docker-compose up -d --build
```

Проверить работу сервера (для контейнера TF не работает):
```sh
docker-compose exec jupyter-sci jupyter server list
```

Читать больше:

- https://jupyter-docker-stacks.readthedocs.io/en/latest/using/selecting.html#jupyter-datascience-notebook
- https://docs.docker.com/compose/gpu-support/
- https://catalog.ngc.nvidia.com/orgs/nvidia/containers/tensorflow

