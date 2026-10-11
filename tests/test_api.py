"""End-to-End and Unit API Tests for Nursing Exam Application."""
import json
import os
import shutil
import tempfile
import time
import unittest

# Point to temporary data directory for clean test runs
test_data_dir = tempfile.mkdtemp()
os.environ["DATA_DIR"] = test_data_dir
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin1234"
os.environ["PER_SUBJECT"] = "20"
os.environ["PASS_PERCENT"] = "70"

from app import app, init_db, load_questions, SUBJECTS, QUESTIONS

class TestNursingExamApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        load_questions()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(test_data_dir, ignore_errors=True)

    def test_01_question_bank_loaded(self):
        self.assertEqual(len(SUBJECTS), 9, "Must have exactly 9 subjects")
        self.assertEqual(len(QUESTIONS), 900, "Must have exactly 900 questions")
        for sid in range(1, 10):
            self.assertIn(sid, SUBJECTS)
            self.assertEqual(len(SUBJECTS[sid]["ids"]), 100, f"Subject {sid} must have 100 questions")

    def test_02_admin_login_and_logout(self):
        client = app.test_client()
        res = client.post("/api/login", json={"username": "admin", "password": "wrongpassword"})
        self.assertEqual(res.status_code, 401)

        res = client.post("/api/login", json={"username": "admin", "password": "admin1234"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["user"]["role"], "admin")
        self.assertIn("sid", res.headers.get("Set-Cookie", ""))

        # Logout cleanly
        res = client.post("/api/logout")
        self.assertEqual(res.status_code, 200)

    def test_03_admin_create_user_and_single_session_enforcement(self):
        admin = app.test_client()
        res = admin.post("/api/login", json={"username": "admin", "password": "admin1234"})
        self.assertEqual(res.status_code, 200)

        # Create student user (API returns 201 Created)
        res = admin.post("/api/admin/users", json={
            "username": "nurse_student1",
            "password": "password123",
            "display_name": "พยาบาลสมหญิง"
        })
        self.assertIn(res.status_code, (200, 201))

        # Logout admin
        admin.post("/api/logout")

        # Client 1 logs in as student
        c1 = app.test_client()
        res1 = c1.post("/api/login", json={"username": "nurse_student1", "password": "password123"})
        self.assertEqual(res1.status_code, 200)

        # Client 2 tries to log in simultaneously with same username -> must be rejected (409 Conflict)
        c2 = app.test_client()
        res2 = c2.post("/api/login", json={"username": "nurse_student1", "password": "password123"})
        self.assertEqual(res2.status_code, 409, "Must reject duplicate concurrent login")
        self.assertIn("กำลังถูกใช้งานอยู่", res2.get_json()["error"])

        # Client 1 logs out -> now Client 2 can log in
        c1.post("/api/logout")
        res3 = c2.post("/api/login", json={"username": "nurse_student1", "password": "password123"})
        self.assertEqual(res3.status_code, 200, "Can log in after previous session logged out")
        c2.post("/api/logout")

    def test_04_exam_generation_and_scoring(self):
        student = app.test_client()
        student.post("/api/login", json={"username": "nurse_student1", "password": "password123"})

        # Start exam for Subject 1 (20 items)
        res = student.post("/api/exam/start", json={"subject_id": 1})
        self.assertEqual(res.status_code, 200)
        exam_data = res.get_json()["exam"]
        exam_id = exam_data["id"]
        
        # Verify exam structure: 20 questions for Subject 1
        items = exam_data["items"]
        self.assertEqual(len(items), 20, "Exam must contain 20 questions per subject")
        self.assertEqual(exam_data["total"], 20)
        self.assertEqual(exam_data["subject_id"], 1)

        # Verify no answers/explanations leaked in exam payload
        for item in items:
            self.assertNotIn("a", item, "Correct answer must not be leaked")
            self.assertNotIn("e", item, "Explanation must not be leaked")
            self.assertEqual(len(item["choices"]), 4, "Must have 4 choices")

        # Answer only first 5 questions (incomplete)
        for pos in range(1, 6):
            res = student.post("/api/exam/answer", json={"exam_id": exam_id, "pos": pos, "chosen": 0})
            self.assertEqual(res.status_code, 200)

        # Anti-cheating: Submitting incomplete exam MUST return 400 Bad Request
        res = student.post("/api/exam/submit", json={"exam_id": exam_id})
        self.assertEqual(res.status_code, 400, "Must block submit when questions are unanswered")
        self.assertIn("ไม่ครบ", res.get_json()["error"])

        # Complete the remaining questions (6 to 20)
        for pos in range(6, 21):
            res = student.post("/api/exam/answer", json={"exam_id": exam_id, "pos": pos, "chosen": 1})
            self.assertEqual(res.status_code, 200)

        # Now submit exam -> returns {ok: True, exam_id: exam_id}
        res = student.post("/api/exam/submit", json={"exam_id": exam_id})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        # View exam details/results immediately with answers & explanations
        res = student.get(f"/api/exams/{exam_id}")
        self.assertEqual(res.status_code, 200)
        detail = res.get_json()["result"]
        self.assertEqual(detail["total"], 20)
        self.assertIn("score", detail)
        self.assertIn("percent", detail)
        self.assertIn("passed", detail)
        self.assertEqual(len(detail["subjects"]), 1, "Must have summary for Subject 1")
        self.assertEqual(detail["subjects"][0]["id"], 1)
        
        # Answers and explanations revealed immediately
        self.assertIn("correct", detail["items"][0])
        self.assertIn("explanation", detail["items"][0])

        student.post("/api/logout")

    def test_05_admin_oversight_and_export(self):
        admin = app.test_client()
        res = admin.post("/api/login", json={"username": "admin", "password": "admin1234"})
        self.assertEqual(res.status_code, 200)

        # Admin stats
        res = admin.get("/api/admin/stats")
        self.assertEqual(res.status_code, 200)
        stats = res.get_json()
        self.assertGreaterEqual(stats["users"], 2)
        self.assertGreaterEqual(stats["exams_submitted"], 1)

        # Admin list exams
        res = admin.get("/api/admin/exams")
        self.assertEqual(res.status_code, 200)
        exams = res.get_json()["exams"]
        self.assertGreaterEqual(len(exams), 1)

        # Admin export CSV
        res = admin.get("/api/admin/exams.csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res.headers.get("Content-Type", ""))
        csv_content = res.data.decode("utf-8-sig")
        self.assertIn("nurse_student1", csv_content)
        self.assertIn("การพยาบาล", csv_content)

        admin.post("/api/logout")

if __name__ == "__main__":
    unittest.main()
