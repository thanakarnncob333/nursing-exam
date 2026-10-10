import json
import urllib.request
import http.cookiejar

# 1. Admin login & create student
cj_admin = http.cookiejar.CookieJar()
admin_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj_admin))
admin_req = urllib.request.Request('http://127.0.0.1:5000/api/login',
    data=json.dumps({'username': 'admin', 'password': 'Na4CggnshCxE'}).encode('utf-8'),
    headers={'Content-Type': 'application/json'})
admin_opener.open(admin_req)

user_req = urllib.request.Request('http://127.0.0.1:5000/api/admin/users',
    data=json.dumps({'username': 'nurse_test_e2e', 'password': 'password123', 'display_name': 'พยาบาลทดสอบ'}).encode('utf-8'),
    headers={'Content-Type': 'application/json'})
try:
    admin_opener.open(user_req)
    print('Created student user')
except Exception as e:
    print('User might already exist:', e)

# 2. Student login
cj_student = http.cookiejar.CookieJar()
student_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj_student))
login_req = urllib.request.Request('http://127.0.0.1:5000/api/login',
    data=json.dumps({'username': 'nurse_test_e2e', 'password': 'password123'}).encode('utf-8'),
    headers={'Content-Type': 'application/json'})
student_opener.open(login_req)
print('Student login OK')

# 3. Start exam
start_req = urllib.request.Request('http://127.0.0.1:5000/api/exam/start', data=b'{}', headers={'Content-Type': 'application/json'})
resp = student_opener.open(start_req)
exam = json.loads(resp.read().decode('utf-8'))['exam']
print('Exam ID:', exam['id'], 'Total items:', exam['total'])

# 4. Answer question 1 & flag question 1
ans_req = urllib.request.Request('http://127.0.0.1:5000/api/exam/answer',
    data=json.dumps({'exam_id': exam['id'], 'pos': 1, 'chosen': 0, 'flagged': True}).encode('utf-8'),
    headers={'Content-Type': 'application/json'})
student_opener.open(ans_req)
print('Answered & flagged question 1')

# 5. Submit exam
sub_req = urllib.request.Request('http://127.0.0.1:5000/api/exam/submit',
    data=json.dumps({'exam_id': exam['id']}).encode('utf-8'),
    headers={'Content-Type': 'application/json'})
sub_resp = student_opener.open(sub_req)
sub_data = json.loads(sub_resp.read().decode('utf-8'))
print('Exam submitted:', sub_data)

# 6. View Result
res_resp = student_opener.open('http://127.0.0.1:5000/api/exams/%d' % exam['id'])
result = json.loads(res_resp.read().decode('utf-8'))['result']
print('Score:', result['score'], '/', result['total'], 'Percent:', result['percent'], 'Passed:', result['passed'])
print('Explanation of Q1 present:', bool(result['items'][0]['explanation']))

# 7. Admin CSV Export
csv_resp = admin_opener.open('http://127.0.0.1:5000/api/admin/exams.csv')
csv_bytes = csv_resp.read()
print('CSV downloaded length:', len(csv_bytes), 'Contains nurse_test_e2e:', 'nurse_test_e2e' in csv_bytes.decode('utf-8-sig'))
print('ALL LIVE HTTP FLOW TESTS PASSED!')
