from pydantic import BaseModel, Field
from typing import List, Optional

class SecondaryID(BaseModel):
    secondary_id: Optional[str] = None
    identifier: Optional[str] = None

class ContactDetails(BaseModel):
    name: Optional[str] = None
    designation: Optional[str] = None
    affiliation: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[str] = None

class Sponsor(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    type_of_sponsor: Optional[str] = None

class SecondarySponsor(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None

class SiteOfStudy(BaseModel):
    pi_name: Optional[str] = None
    site_name: Optional[str] = None
    site_address: Optional[str] = None
    contact_details: Optional[str] = None

class EthicsCommittee(BaseModel):
    committee_name: Optional[str] = None
    approval_status: Optional[str] = None

class RegulatoryClearance(BaseModel):
    status: Optional[str] = None

class HealthCondition(BaseModel):
    health_type: Optional[str] = None
    condition: Optional[str] = None

class Intervention(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    details: Optional[str] = None

class InclusionCriteria(BaseModel):
    age_from: Optional[str] = None
    age_to: Optional[str] = None
    gender: Optional[str] = None
    details: Optional[str] = None

class ExclusionCriteria(BaseModel):
    details: Optional[str] = None

class Outcome(BaseModel):
    outcome: Optional[str] = None
    timepoints: Optional[str] = None

class TargetSampleSize(BaseModel):
    total_sample_size: Optional[str] = None
    sample_size_india: Optional[str] = None
    final_enrollment_total: Optional[str] = None
    final_enrollment_india: Optional[str] = None

class TrialDuration(BaseModel):
    years: Optional[str] = None
    months: Optional[str] = None
    days: Optional[str] = None

class ClinicalTrial(BaseModel):
    ctri_number: str
    registration_date: Optional[str] = None
    retrospective_registration: bool = False
    last_modified_on: Optional[str] = None
    post_graduate_thesis: Optional[str] = None
    type_of_trial: Optional[str] = None
    type_of_study: Optional[str] = None
    study_design: Optional[str] = None
    public_title: Optional[str] = None
    scientific_title: Optional[str] = None
    trial_acronym: Optional[str] = None
    
    secondary_ids: List[SecondaryID] = Field(default_factory=list)
    principal_investigator: Optional[ContactDetails] = None
    contact_person_scientific: Optional[ContactDetails] = None
    contact_person_public: Optional[ContactDetails] = None
    
    sources_of_monetary_support: List[str] = Field(default_factory=list)
    primary_sponsor: Optional[Sponsor] = None
    secondary_sponsors: List[SecondarySponsor] = Field(default_factory=list)
    countries_of_recruitment: List[str] = Field(default_factory=list)
    
    sites_of_study: List[SiteOfStudy] = Field(default_factory=list)
    ethics_committees: List[EthicsCommittee] = Field(default_factory=list)
    regulatory_clearance_dcgi: Optional[RegulatoryClearance] = None
    
    health_conditions: List[HealthCondition] = Field(default_factory=list)
    interventions: List[Intervention] = Field(default_factory=list)
    
    inclusion_criteria: Optional[InclusionCriteria] = None
    exclusion_criteria: Optional[ExclusionCriteria] = None
    
    method_random_sequence: Optional[str] = None
    method_concealment: Optional[str] = None
    blinding_masking: Optional[str] = None
    
    primary_outcomes: List[Outcome] = Field(default_factory=list)
    secondary_outcomes: List[Outcome] = Field(default_factory=list)
    
    target_sample_size: Optional[TargetSampleSize] = None
    phase: Optional[str] = None
    
    first_enrollment_date_india: Optional[str] = None
    study_completion_date_india: Optional[str] = None
    first_enrollment_date_global: Optional[str] = None
    study_completion_date_global: Optional[str] = None
    
    duration: Optional[TrialDuration] = None
    recruitment_status_global: Optional[str] = None
    recruitment_status_india: Optional[str] = None
    publication_details: Optional[str] = None
    ipd_sharing_statement: Optional[str] = None
    summary: Optional[str] = None
