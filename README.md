# RutasGen · Paquetes POI sin conexión

Distribución de datos públicos de OpenStreetMap para RutasGen Android.
Este repositorio no contiene el proyecto Android ni datos de sus usuarios.

## Estado

El proceso genera Francia e Italia y publica una versión solo después de pasar
las pruebas y comprobar ambos SQLite. La existencia del repositorio o de una
ejecución en Actions NO significa que ya haya paquetes publicados.

Consultar [Actions](../../actions) y [Releases](../../releases).
Cuando exista una versión publicada, el catálogo estable será:

https://github.com/kartoonberg-spec/rutasgen-poi-packages/releases/latest/download/catalog-v1.json

La app Android necesita una integración adicional para consultar este catálogo,
ofrecer descargas según GPS e instalar los archivos. Crear este repositorio no
actualiza los APK ya instalados.

## Generación

En GitHub: Actions → Preparar POI Francia e Italia → Run workflow.
También se ejecuta al cambiar herramientas o selectores en main.
No hay calendario automático ni credenciales externas que configurar.

En Linux con Python 3.12 y osmium-tool, instalar requirements.txt y ejecutar:

```sh
python -m unittest discover -s tools -v
python tools/publish_packages.py --repository kartoonberg-spec/rutasgen-poi-packages --tag prueba-local
```

La segunda orden genera archivos locales, no publica nada. Requiere varios GB
de descarga y espacio temporal; Francia e Italia se procesan secuencialmente.

## Formato y garantías

- SQLite `rutasgen-osm-poi-v1`, compatible con el instalador existente.
- Cada archivo debe ocupar como máximo 1 GiB; si supera el límite, el proceso
  se detiene para dividir la zona, sin publicar una descarga incompatible.
- Cobertura GeoJSON tomada del límite Geofabrik, nunca inferida de los POI.
- Se conserva la fecha del extracto y la firma de los selectores.
- Las omisiones de geometrías dejan `complete=false`; no se ocultan errores
  para afirmar que la cobertura es completa.
- Prefiltrado osmium con dependencias; después, resolución mediante caché
  SQLite y detección de ciclos/límites. No utiliza Overpass.
- Se suben primero todos los archivos a un borrador y después se publica.
  Un fallo anterior no sustituye la última versión publicada.
- El catálogo contiene SHA-256 y tamaño. La app deberá verificarlos antes de
  instalar. Un hash no equivale a validar recompensas o identidad en servidor.

## Licencia de datos

© OpenStreetMap contributors · ODbL 1.0. Extractos: Geofabrik.
Ver RELEASE_NOTES.md. Los datos derivados conservan la atribución OSM.

El archivo Kotlin de catalog/ es una copia de los selectores que utiliza la
versión de RutasGen revisada; no se compila como aplicación. Al cambiar las
categorías de la app hay que regenerar y comprobar la compatibilidad.
