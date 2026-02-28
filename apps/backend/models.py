from sqlalchemy import Column,Integer,String,Float

from apps.backend.database import Base


class User(Base):

    __tablename__="users"

    id=Column(Integer,primary_key=True)

    email=Column(String,unique=True)

    password=Column(String)


class Product(Base):

    __tablename__="products"

    id=Column(Integer,primary_key=True)

    name=Column(String)

    price=Column(Float)


class Order(Base):

    __tablename__="orders"

    id=Column(Integer,primary_key=True)

    user_id=Column(Integer)

    total=Column(Float)
