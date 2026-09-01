# Mother Base — Supply Command Center

Centro de comando de Supply construido en Streamlit. La primera versión incluye:

- Acceso **Big Boss** con contraseña.
- Acceso **Raiden** sin contraseña.
- Módulo **Les Enfants Terribles** para planeación.
- Módulo **Militaires Sans Frontières** reservado para reporting.
- Naked, Solidus y Liquid Engines bajo un único límite global de tareas.
- Lectura automática del Google Sheet público `DATA_TRANSFERS`.
- Carga y consolidación de uno o varios CSV de Fountain9 de hasta 500 MB cada uno.
- Excel operativo, CSV independiente por origen, ZIP y PDF ejecutivo.

## Estructura

```text
mother_base/
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── engines/
│   ├── __init__.py
│   ├── liquid_engine.py
│   ├── mission_control.py
│   ├── naked_engine.py
│   └── solidus_engine.py
├── modules/
│   ├── __init__.py
│   ├── les_enfants_terribles.py
│   └── militaires_sans_frontieres.py
├── app.py
├── auth.py
├── modelo_abasto.py
├── mother_base_theme.py
├── requirements.txt
├── requirements-dev.txt
└── runtime.txt
```

## Engines

### Naked Engine

Procesa únicamente la recomendación natural de Fountain9. Tiene la primera
prioridad de consumo de stock, capacidad y tareas.

### Solidus Engine

Procesa las reglas manuales de forecast 0 y, cuando se activan, cobertura AVL y
prevención de quiebres. Solo utiliza el presupuesto que quede después de Naked.

### Liquid Engine

Se ejecuta al final. Puede:

- Agotar automáticamente remanentes de 1 a 9 unidades por origen–SKU.
- Procesar una lista manual de SKUs para liquidar.
- Nivelar primero el DOH de las tiendas hasta un máximo de 14.
- Distribuir el excedente posterior con el share general de ventas.

Liquid solo considera tiendas presentes en los CSV de la misión del día. Para
esta lógica el producto no necesita aparecer en `CATALOGO`.

Los SKUs manuales se capturan de forma independiente para cada warehouse origen
seleccionado. Si el SKU 10087 se captura solamente en el cuadro del origen 444,
Liquid no utilizará el stock disponible del mismo SKU en 831.

La limpieza automática de remanentes también permite seleccionar en cuáles
orígenes debe operar. De esta forma, un saldo menor a 10 unidades puede agotarse
en 444 sin activar la misma regla para 831.

Los tres motores comparten el mismo límite:

```text
TAREAS NAKED + TAREAS SOLIDUS + TAREAS LIQUID <= MAX_TASKS
```

Una tarea corresponde a una combinación origen–destino–SKU. Si Liquid agrega
unidades sobre una combinación que ya existe, aumenta su cantidad sin crear una
tarea nueva.

## Navegación

Mother Base no utiliza barra lateral. Después de seleccionar Big Boss o Raiden,
la pantalla principal permite entrar a un módulo. Dentro del módulo no existe un
botón de regreso; para reiniciar el acceso y volver a la portada se recarga la
página.

La aplicación conserva la paleta original del Transfer Planner: fondo papel,
negro, verde ácido, coral y azul.

## Hoja SHARE_VENTAS

Liquid Engine requiere una pestaña llamada `SHARE_VENTAS` dentro de
`DATA_TRANSFERS`:

| WAREHOUSE_ID | SHARE |
|---:|---:|
| 105 | 0.12 |
| 210 | 0.08 |

El share puede venir como proporción (`0.12`) o porcentaje (`12`). El motor lo
usa como ponderador y lo normaliza únicamente entre las tiendas elegibles.

## Archivos de Fountain9

Cada CSV debe contener:

- `Warehouseid` o `Node_Store`.
- `SKU ID`.
- `Predicted Demand for selected duration`.
- `Predicted Opening Inventory`.
- `Replenishment Quantity for Plan Duration (MOV)`.
- `Net Inter-Store Transfers`.

El resto de las dimensiones se obtiene de `DATA_TRANSFERS`.

## Ejecución local

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

La contraseña predeterminada de Big Boss es `Admin`. Para no dejarla dentro del
código, copia `.streamlit/secrets.toml.example` como `.streamlit/secrets.toml`.

## Publicación en Streamlit Community Cloud

1. Sube el contenido de esta carpeta a la raíz de un repositorio de GitHub.
2. En Streamlit Community Cloud selecciona `Create app`.
3. Elige el repositorio, la rama `main` y `app.py` como archivo principal.
4. En `App settings > Secrets` agrega:

```toml
BIG_BOSS_PASSWORD = "Admin"
```

5. Despliega la aplicación.

No se requieren APIs de pago ni credenciales de Google mientras
`DATA_TRANSFERS` permanezca público para lectura.

## Regla de capacidad

Todos los engines aplican capacidad estricta en m³. Ninguna línea puede hacer
que una tienda exceda su capacidad disponible:

```text
unidades máximas = floor(capacidad restante m³ / volumen m³ por unidad)
```
