# RutasGen · Paquetes POI sin conexión

Distribución de datos públicos de OpenStreetMap para RutasGen Android.
Este repositorio no contiene el proyecto Android ni datos de sus usuarios.

## Estado

El proceso prepara los países y regiones de `catalog/regions.json`. Cada región
se genera por separado, con un máximo de dos trabajos simultáneos. Se mantienen
los paquetes ya publicados y solo se añade al catálogo lo que supera las comprobaciones. La existencia del repositorio o de una
ejecución en Actions NO significa que ya haya paquetes publicados.

Consultar [Actions](../../actions) y [Releases](../../releases).
Cuando exista una versión publicada, el catálogo estable será:

https://github.com/kartoonberg-spec/rutasgen-poi-packages/releases/latest/download/catalog-v1.json

La app Android necesita una integración adicional para consultar este catálogo,
ofrecer descargas según GPS e instalar los archivos. Crear este repositorio no
actualiza los APK ya instalados.

## Generación

En GitHub: Actions → Preparar POI Europa → Run workflow.
También se ejecuta al cambiar herramientas o selectores en main.
No hay calendario automático ni credenciales externas que configurar.

En Linux con Python 3.12 y osmium-tool, instalar requirements.txt y ejecutar:

```sh
python -m unittest discover -s tools -v
python tools/publish_packages.py --repository kartoonberg-spec/rutasgen-poi-packages --tag prueba-local --region portugal
```

La segunda orden genera archivos locales, no publica nada. Requiere varios GB
de descarga y espacio temporal según el país.

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

## Ampliación europea

La matriz omite las identidades que ya figuran en el catálogo publicado: no vuelve
 a generar Francia e Italia para añadir otro país. Alemania se divide por estados,
Reino Unido por Inglaterra/Escocia/Gales y el extracto compartido Irlanda/Irlanda
del Norte; Rusia se limita a los distritos occidentales configurados. Se incluyen
extractos insulares y del Cáucaso. Los nombres y geometrías describen extractos de
Geofabrik, no una declaración de fronteras ni cobertura garantizada de territorios
ultramarinos. San Marino y Vaticano no tienen paquete separado en este lote; debe
consultarse la cobertura del extracto de Italia.

Cada región correcta se publica en su propia release SIN marcarla como latest.
Al terminar la matriz, incluso si alguna región ha fallado, se fusionan los éxitos
con el catálogo anterior. Se verifica tamaño y digest del asset publicado. Solo el
catálogo combinado se marca latest: así la app mantiene una dirección estable y
los enlaces versionados anteriores no desaparecen. Hasta esa fusión, la app sigue
viendo el catálogo anterior. Las regiones fallidas se vuelven a intentar con otra
ejecución. No se afirma que un país esté disponible por estar en regions.json.

Este proceso configura generación de países nuevos, no actualizaciones periódicas
de paquetes existentes. Para actualizarlos hace falta un flujo explícito posterior.
La marca de cobertura parcial permanece si hay geometrías no resueltas; en esos
casos la app conserva su alternativa de red. Las pruebas Python no validan Android.
