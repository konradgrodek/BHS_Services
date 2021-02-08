from flask import Flask, jsonify
from BHSJsonBean import *
from datetime import datetime


app = Flask(__name__)


@app.route('/')
def hello():
    t = TemperatureReadingJson(36.6, datetime.now(), 'Office', 'a8f3b11')
    jsn = jsonify(t.to_dict())
    return jsn


if __name__ == '__main__':
    app.run(host='0.0.0.0')
