from app.core.security import hash_password
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database

PASSWORD="Outreach-Cohort-2026!"

def setup_function(): reset_database()

def seed():
    with TestingSessionLocal() as db:
        org=Organization(name="Founder Org",slug="founder-org"); other=Organization(name="Other Org",slug="other-org")
        db.add_all([org,other]); db.flush()
        u=User(organization_id=org.id,email="founder@example.com",full_name="Founder",password_hash=hash_password(PASSWORD),role=UserRole.ADMIN,is_active=True)
        o=User(organization_id=other.id,email="other@example.com",full_name="Other",password_hash=hash_password(PASSWORD),role=UserRole.ADMIN,is_active=True)
        db.add_all([u,o]); db.commit(); return org.id, other.id

def login(slug="founder-org", email="founder@example.com"):
    r=client.post("/api/v1/auth/login",json={"organization_slug":slug,"email":email,"password":PASSWORD}); assert r.status_code==200, r.text

def test_qualification_score_and_cohort_targets():
    seed(); login()
    a=client.post("/api/v1/outreach/accounts",json={"name":"A Marine Insurer","account_type":"marine_insurer","machinery_claim_volume_score":5,"pain_intensity_score":5,"buyer_access_score":4,"data_availability_score":4,"security_fit_score":4,"pilot_willingness_score":4})
    assert a.status_code==201, a.text
    assert a.json()["qualification_score"] >= 75
    b=client.post("/api/v1/outreach/accounts",json={"name":"B Ship Manager","account_type":"ship_manager","machinery_claim_volume_score":4,"pain_intensity_score":4,"buyer_access_score":3,"data_availability_score":4,"security_fit_score":3,"pilot_willingness_score":3})
    assert b.status_code==201
    cohort=client.get("/api/v1/outreach/cohort"); assert cohort.status_code==200, cohort.text
    body=cohort.json(); assert body["target_qualified_partners"]==3; assert body["target_paid_pilots"]==1; assert body["accounts_total"]==2; assert body["accounts"][0]["qualification_band"]=="A"

def test_stage_progress_and_paid_pilot_offer_versioning():
    seed(); login()
    account=client.post("/api/v1/outreach/accounts",json={"name":"Pilot Insurer","account_type":"marine_insurer","machinery_claim_volume_score":5,"pain_intensity_score":5,"buyer_access_score":5,"data_availability_score":5,"security_fit_score":4,"pilot_willingness_score":5}).json()
    upd=client.patch(f"/api/v1/outreach/accounts/{account['id']}",json={"stage":"pilot_qualified","next_step":"Schedule controlled pilot"}); assert upd.status_code==200
    contact=client.post(f"/api/v1/outreach/accounts/{account['id']}/contacts",json={"name":"Head of Claims","title":"Head of Marine Claims","email":"claims@example.com","role_type":"buyer"}); assert contact.status_code==201
    touch=client.post(f"/api/v1/outreach/accounts/{account['id']}/touches",json={"contact_id":contact.json()["id"],"channel":"warm_intro","status":"meeting_booked","message_summary":"Discovery meeting booked"}); assert touch.status_code==201
    payload={"duration_days":30,"fee":10000,"currency":"USD","scope":"Controlled H&M machinery claims pilot for up to ten claims.","deliverables":["onboarding","pilot scorecard"],"customer_responsibilities":["provide anonymized files"],"success_criteria":["time reduction >=30%"],"exclusions":["automated coverage decisions"]}
    one=client.post(f"/api/v1/outreach/accounts/{account['id']}/pilot-offers",json=payload); two=client.post(f"/api/v1/outreach/accounts/{account['id']}/pilot-offers",json=payload)
    assert one.status_code==201 and one.json()["version"]==1; assert two.status_code==201 and two.json()["version"]==2
    cohort=client.get("/api/v1/outreach/cohort").json(); assert cohort["pilot_qualified"]==1

def test_outreach_is_tenant_scoped():
    seed(); login()
    account=client.post("/api/v1/outreach/accounts",json={"name":"Private Target","account_type":"ship_manager"}).json()
    client.cookies.clear(); login("other-org","other@example.com")
    hidden=client.patch(f"/api/v1/outreach/accounts/{account['id']}",json={"stage":"contacted"}); assert hidden.status_code==404
