from sqlalchemy import create_engine, Column, Integer, ForeignKey, String
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
    relationship,
    selectinload,
    with_polymorphic,
)
from sqlalchemy import select

Base = declarative_base()


class Server(Base):
    __tablename__ = "server"
    id = Column(Integer, primary_key=True)


class Inbound(Base):
    __tablename__ = "inbound"
    id = Column(Integer, primary_key=True)
    type = Column(String(50))
    server_id = Column(Integer, ForeignKey("server.id"))
    server = relationship("Server")
    __mapper_args__ = {"polymorphic_on": type, "polymorphic_identity": "base"}


class InboundConnection(Base):
    __tablename__ = "inbound_connection"
    id = Column(Integer, primary_key=True)
    inbound_id = Column(Integer, ForeignKey("inbound.id"))
    inbound = relationship("Inbound")


engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

conn_poly = with_polymorphic(InboundConnection, "*")
inbound_poly = with_polymorphic(Inbound, "*")

stmt = select(conn_poly).options(
    selectinload(conn_poly.inbound.of_type(inbound_poly)).selectinload(inbound_poly.server)
)
print("Statement compiled OK!")

# Execute to ensure no runtime error
session.execute(stmt)
print("Statement executed OK!")
