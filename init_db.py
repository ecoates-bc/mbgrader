from app import db, Datatype

db.drop_all()
db.create_all()

numeric = Datatype(name='numeric',extension='csv')
text = Datatype(name='text',extension='txt')
symbolic = Datatype(name='symbolic',extension='sym')

db.session.add(numeric)
db.session.add(text)
db.session.add(symbolic)

db.session.commit()