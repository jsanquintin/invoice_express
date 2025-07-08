from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import List, Optional
from datetime import timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import psycopg2
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

# Configuración de seguridad
app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Usuario fijo (clave123)
fake_user = {
    "username": "admin",
    "hashed_password": "$2a$12$ySnu7TMYP8IKn/OFUBOCC.LUV/4IciZZf/ZsZBsewEUHZ5eNSug3K"
}

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    return jwt.encode(data.copy(), SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")

def get_db():
    return psycopg2.connect(DATABASE_URL)

# Esquemas
class Cliente(BaseModel):
    nombre: str
    documento: str
    direccion: str

class Producto(BaseModel):
    nombre: str
    precio: float

class DetalleItem(BaseModel):
    producto_id: int
    cantidad: int
    precio_unitario: float

class Factura(BaseModel):
    cliente_id: int
    metodo_pago: str
    monto_recibido: Optional[float] = 0
    descuento: Optional[float] = 0
    items: List[DetalleItem]

# Login
@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username != fake_user["username"] or not verify_password(form_data.password, fake_user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")
    token = create_access_token(data={"sub": form_data.username})
    return {"access_token": token, "token_type": "bearer"}

# Crear cliente
@app.post("/clientes", dependencies=[Depends(get_current_user)])
def crear_cliente(cliente: Cliente):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO clientes (nombre, documento, direccion) VALUES (%s, %s, %s)", (cliente.nombre, cliente.documento, cliente.direccion))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Cliente creado"}

# Buscar cliente
@app.get("/cliente/{documento}", dependencies=[Depends(get_current_user)])
def buscar_cliente(documento: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, nombre, direccion FROM clientes WHERE documento = %s", (documento,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return {"id": result[0], "nombre": result[1], "direccion": result[2]}

# Crear producto
@app.post("/productos", dependencies=[Depends(get_current_user)])
def crear_producto(producto: Producto):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO productos (nombre, precio) VALUES (%s, %s)", (producto.nombre, producto.precio))
    conn.commit()
    cur.close()
    conn.close()
    return {"mensaje": "Producto creado"}

# Listar productos
@app.get("/productos", dependencies=[Depends(get_current_user)])
def listar_productos():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, nombre, precio FROM productos")
    productos = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": p[0], "nombre": p[1], "precio": p[2]} for p in productos]

# Crear factura
@app.post("/facturas", dependencies=[Depends(get_current_user)])
def crear_factura(factura: Factura):
    conn = get_db()
    cur = conn.cursor()
    subtotal = sum(item.cantidad * item.precio_unitario for item in factura.items)
    descuento = factura.descuento or 0
    itbis = (subtotal - descuento) * 0.18
    total = subtotal - descuento + itbis
    cambio = factura.monto_recibido - total if factura.metodo_pago.lower() == "efectivo" else 0

    cur.execute("""
        INSERT INTO facturas (cliente_id, fecha, subtotal, itbis, total, metodo_pago, monto_recibido, cambio)
        VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s) RETURNING id
    """, (factura.cliente_id, subtotal, itbis, total, factura.metodo_pago, factura.monto_recibido, cambio))
    factura_id = cur.fetchone()[0]

    for item in factura.items:
        cur.execute("""
            INSERT INTO detalle_factura (factura_id, producto_id, cantidad, precio_unitario, total)
            VALUES (%s, %s, %s, %s, %s)
        """, (factura_id, item.producto_id, item.cantidad, item.precio_unitario, item.cantidad * item.precio_unitario))

    conn.commit()
    cur.close()
    conn.close()

    return {"mensaje": "Factura creada", "factura_id": factura_id, "total": total, "cambio": cambio}
