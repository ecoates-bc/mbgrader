from flask import Flask, render_template, jsonify, request, url_for, redirect
from flask_sqlalchemy import SQLAlchemy

import os
from glob import glob
import numpy as np
import pandas as pd

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

@app.route('/')
def index():
    return render_template('index.html')

##################################################
## API
##################################################

@app.route('/assignments', methods=['GET','POST'])
def assignments():
    if request.method == 'GET':
        assignments = Assignment.query.all()
        return jsonify([assignment.to_dict() for assignment in assignments])
    elif request.method == 'POST':
        assignment = Assignment(name=request.json['name'])
        db.session.add(assignment)
        db.session.commit()
        assignment.load_submissions()
        return jsonify(assignment.to_dict())

@app.route('/assignments/<int:assignment_id>', methods=['GET','DELETE'])
def assignment(assignment_id):
    if request.method == 'GET':
        assignment = Assignment.query.get_or_404(assignment_id)
        return jsonify(assignment.to_dict())
    if request.method == 'DELETE':
        assignment = Assignment.query.get(assignment_id)
        if assignment:
            db.session.delete(assignment)
            db.session.commit()
            return ('',204)
        else:
            return ('',204)

@app.route('/assignments/<int:assignment_id>/grades')
def grades(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    assignment.save_grades()
    return ('',200)

@app.route('/assignments/<int:assignment_id>/questions', methods=['GET','POST'])
def questions(assignment_id):
    if request.method == 'GET':
        questions = Question.query.filter_by(assignment_id=assignment_id).all()
        return jsonify([question.to_dict() for question in questions])
    elif request.method == 'POST':
        question = Question(name=request.json['name'],
                            var_name=request.json['var_name'],
                            max_grade=request.json['max_grade'],
                            tolerance=request.json['tolerance'],
                            preprocessing=request.json['preprocessing'],
                            assignment_id=assignment_id)
        db.session.add(question)
        db.session.commit()
        return jsonify(question.to_dict())

@app.route('/assignments/<int:assignment_id>/questions/<int:question_id>', methods=['GET','DELETE'])
def question(assignment_id,question_id):
    if request.method == 'GET':
        question = Question.query.get_or_404(question_id)
        return jsonify(question.to_dict())
    if request.method == 'DELETE':
        question = Question.query.get(question_id)
        if question:
            db.session.delete(question)
            db.session.commit()
            return ('',204)
        else:
            return ('',204)

@app.route('/assignments/<int:assignment_id>/questions/<int:question_id>/batches', methods=['GET'])
def batch(assignment_id,question_id):
    create = request.args.get('create')
    if request.method == 'GET' and create == 'true':
        question = Question.query.get_or_404(question_id)
        question.delete_batches()
        question.create_batches()
        return jsonify([batch.to_dict() for batch in question.batches])
    elif request.method == 'GET' and create == 'false':
        question = Question.query.get_or_404(question_id)
        return jsonify([batch.to_dict() for batch in question.batches])

@app.route('/assignments/<int:assignment_id>/questions/<int:question_id>/batches/<int:batch_id>', methods=['GET','PUT'])
def grade(assignment_id,question_id,batch_id):
    if request.method == 'GET':
        batch = Batch.query.get_or_404(batch_id)
        return jsonify(batch.to_dict())
    elif request.method == 'PUT':
        batch = Batch.query.get_or_404(batch_id)
        batch.grade = int(request.json['grade'])
        batch.comments = request.json['comments']
        db.session.add(batch)
        db.session.commit()
        return jsonify(batch.to_dict())

##################################################
## DATABASE
##################################################

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)

    questions = db.relationship('Question', backref='assignment', lazy=True, cascade='all,delete')
    responses = db.relationship('Response', backref='assignment', lazy=True, cascade='all,delete')
    submissions = db.relationship('Submission', backref='assignment', lazy=True, cascade='all,delete')

    def load_submissions(self):
        student_ids = [int(os.path.basename(s)) for s in glob(os.path.join('submissions',self.name,'*'))]
        for student_id in student_ids:
            student = Student.query.get(student_id)
            if not student:
                student = Student(id=student_id)
            db.session.add(student)
            submission = Submission(assignment_id=self.id,student_id=student_id,grade=0,feedback='')
            db.session.add(submission)
            response_files = [os.path.basename(r) for r in glob(os.path.join('submissions',self.name,str(student_id),'*'))]
            for response_file in response_files:
                var_name, extension = response_file.split('.')
                datatype = Datatype.query.filter_by(extension=extension).first()
                response = Response(assignment_id=self.id,student_id=student_id,datatype_id=datatype.id,var_name=var_name)
                db.session.add(response)
            db.session.commit()

    def total_points(self):
        points = [question.max_grade for question in self.questions]
        return sum(points)

    def total_submissions(self):
        return len(self.submissions)

    def total_questions(self):
        return len(self.questions)

    def save_grades(self):
        assignment_grades_folder = os.path.join('grades',self.name)
        os.makedirs(assignment_grades_folder,exist_ok=True)
        assignment_feedback_folder = os.path.join('feedback',self.name)
        os.makedirs(assignment_feedback_folder,exist_ok=True)
        old_feedback = glob(os.path.join(assignment_feedback_folder,'*.txt'))
        for f in old_feedback:
            os.remove(f)

        q1 = BatchResponse.query.join('batch','question').options(db.joinedload('batch').joinedload('question'))
        q2 = q1.filter_by(assignment_id=self.id)
        q3 = q2.join('response','student').options(db.joinedload('response').joinedload('student'))

        df = pd.read_sql(q3.statement,db.engine)
        columns = ['student_id','grade','comments','name']
        df = df[columns]
        df.columns = ['Student ID','Grade','Comments','Question']

        grades = df.pivot(index='Student ID',columns='Question',values='Grade').fillna(0)
        grades['Total'] = grades.sum(axis=1)
        grades.to_csv(os.path.join(assignment_grades_folder,self.name) + '.csv')

        comments = df.pivot(index='Student ID',columns='Question',values='Comments').fillna('Did not find a response for this question.')
        for student in comments.index:
            filename = os.path.join(assignment_feedback_folder,str(student) + '.txt')
            f = open(filename,'w')
            feedback = ''
            for question in comments.columns:
                comment = comments.loc[student,question]
                grade = grades.loc[student,question]
                max_grade = Question.query.filter_by(assignment_id=self.id).filter_by(name=question).first().max_grade
                feedback += '\n{0}\nGrade: {1}/{2}\nComments: {3}\n'.format(question,grade,float(max_grade),comment)
            f.write(feedback)
            f.close()


    def to_dict(self):
        return {'id': self.id,
                'name': self.name,
                'total_points': self.total_points(),
                'total_questions': self.total_questions(),
                'total_submissions': self.total_submissions()}


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    var_name = db.Column(db.String(80), nullable=False)
    max_grade = db.Column(db.Integer, nullable=False)
    tolerance = db.Column(db.Float, default=0.001)
    preprocessing = db.Column(db.String(280))

    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    batches = db.relationship('Batch', backref='question', lazy=True, cascade='all,delete')

    def delete_batches(self):
        for batch in self.batches:
            db.session.delete(batch)
        db.session.commit()

    def create_batches(self):
        if self.preprocessing:
            f = open(os.path.join('app','preprocessing.py'),'w')
            f.write(self.preprocessing)
            f.close()
            from app.preprocessing import fun
        else:
            fun = None
        responses = Response.query.filter_by(assignment_id=self.assignment_id,var_name=self.var_name).all()
        for response in responses:
            batched = False
            for batch in self.batches:
                if batch.compare(response,preprocessing=fun):
                    this_batch = batch
                    batched = True
                    continue
            if not batched:
                this_batch = Batch(grade=0,comments='',datatype_id=response.datatype_id,question_id=self.id)
                db.session.add(this_batch)
                db.session.commit()
            batch_response = BatchResponse(response_id=response.id,batch_id=this_batch.id)
            db.session.add(batch_response)
            db.session.commit()
        os.remove(os.path.join('app','preprocessing.py'))

    def total_batches(self):
        return len(self.batches)

    def total_responses(self):
        return sum([len(batch.batch_responses) for batch in self.batches])

    def to_dict(self):
        return {'id': self.id,
                'name': self.name,
                'var_name': self.var_name,
                'max_grade': self.max_grade,
                'tolerance': self.tolerance,
                'assignment_id': self.assignment_id,
                'total_batches': self.total_batches(),
                'total_responses': self.total_responses()}


class BatchResponse(db.Model):
    response_id = db.Column(db.Integer, db.ForeignKey('response.id'), primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), primary_key=True)

    response = db.relationship('Response', backref='batch_responses', lazy=True)

class Batch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    grade = db.Column(db.Integer)
    comments = db.Column(db.String(280))

    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    datatype_id = db.Column(db.Integer, db.ForeignKey('datatype.id'), nullable=False)
    batch_responses = db.relationship('BatchResponse', backref='batch', lazy=True, cascade='all,delete')

    def compare(self,response,preprocessing=None):
        if self.datatype.id != response.datatype.id:
            return False
        response_data = response.get_data()
        batch_data = self.get_data()
        if preprocessing:
            try:
                response_data = preprocessing(response.student_id,response_data)
                batch_data = preprocessing(self.batch_responses[0].response.student_id,batch_data)
            except:
                print('Preprocessing failed ... ')
                pass
        dtype = self.datatype.name
        if dtype in ['text','symbolic']:
            return batch_data == response_data
        elif dtype == 'numeric':
            return np.array_equal(batch_data.shape,response_data.shape) and np.allclose(batch_data,response_data,atol=self.question.tolerance)
        else:
            return False

    def total_responses(self):
        return len(self.batch_responses)

    def get_fullfile(self):
        return self.batch_responses[0].response.get_fullfile()

    def get_data(self):
        return self.batch_responses[0].response.get_data()

    def to_dict(self):
        datatype = Datatype.query.get(self.datatype_id).name
        if self.question.preprocessing:
            f = open(os.path.join('app','preprocessing.py'),'w')
            f.write(self.question.preprocessing)
            f.close()
            from app.preprocessing import fun
            try:
                data = fun(self.batch_responses[0].response.student_id,self.get_data())
            except:
                data = self.get_data()
        else:
            data = self.get_data()
        os.remove(os.path.join('app','preprocessing.py'))
        return {'id': self.id,
                'grade': self.grade,
                'comments': self.comments,
                'question_id': self.question_id,
                'assignment_id': self.question.assignment.id,
                'datatype': datatype,
                'total_batch_responses': self.total_responses(),
                'total_question_responses': self.question.total_responses(),
                'data': str(data)}

class Response(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    var_name = db.Column(db.String(80), nullable=False)

    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    datatype_id = db.Column(db.Integer, db.ForeignKey('datatype.id'), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)

    def get_fullfile(self):
        return os.path.join('submissions',self.assignment.name,str(self.student_id),self.var_name + '.' + self.datatype.extension)

    def get_data(self):
        dtype = self.datatype.name
        filename = self.get_fullfile()
        if dtype == 'numeric':
            data = np.loadtxt(filename,delimiter=',',ndmin=2)
            if data.size == 1:
                data = data.flat[0]
        else:
            f = open(filename)
            data = f.read()
            f.close()
        return data

class Datatype(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    extension = db.Column(db.String(10), nullable=False)

    batches = db.relationship('Batch', backref='datatype', lazy=True)
    responses = db.relationship('Response', backref='datatype', lazy=True)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    responses = db.relationship('Response', backref='student', lazy=True)

class Submission(db.Model):
    grade = db.Column(db.Integer)
    feedback = db.Column(db.String(280))

    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), primary_key=True)
    student = db.relationship('Student', backref='submissions', lazy=True)