from internhunter.apply.applicant import Applicant
from internhunter.apply.fields import FormField, classify_fields, field_key

A = Applicant(full_name="Jane Doe", email="jane@x.com", phone="555",
              work_authorization="US Citizen", requires_sponsorship=False,
              linkedin_url="https://linkedin.com/in/jane")


def test_field_key_normalizes_labels():
    assert field_key("First Name") is None or field_key("Full Name") == "full_name"
    assert field_key("Email Address") == "email"
    assert field_key("LinkedIn Profile") == "linkedin_url"


def test_classify_splits_fillable_and_unknown():
    spec = [
        FormField(name="name", label="Full Name", ftype="text", required=True),
        FormField(name="email", label="Email", ftype="email", required=True),
        FormField(name="resume", label="Resume/CV", ftype="file", required=True),
        FormField(name="q1", label="Why do you want to work here?", ftype="textarea", required=True),
        FormField(name="phone", label="Phone", ftype="text", required=False),
    ]
    payload, unknown = classify_fields(spec, A)
    assert payload["name"] == "Jane Doe"
    assert payload["resume"] == "@resume"
    assert [f.name for f in unknown] == ["q1"]   # custom required question is unfillable
