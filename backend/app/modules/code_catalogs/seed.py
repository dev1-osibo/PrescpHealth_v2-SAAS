"""
PrescpHealth Backend — Code Catalog Seed Data.

Seeds the code_catalogs table with a representative subset of clinical codes
from ICD-10, ATC, LOINC, and SNOMED classification systems.

This seed data provides:
- ~50 common ICD-10 disease codes (diabetes, hypertension, stroke, etc.)
- ~30 common ATC drug codes (metformin, amlodipine, atorvastatin, etc.)
- ~30 common LOINC lab codes (glucose, HbA1c, creatinine, etc.)
- ~20 common SNOMED procedure codes (appendectomy, biopsy, etc.)

Multilingual Support:
    French and Portuguese translations are included for the most common
    codes to support francophone and lusophone African clinicians.

Idempotency:
    Uses INSERT ... ON CONFLICT DO NOTHING to ensure running the seed
    function multiple times produces no duplicates. Safe to call on
    every application startup or migration.

Usage:
    from app.modules.code_catalogs.seed import seed_code_catalogs

    async with get_session() as db:
        await seed_code_catalogs(db)
"""

import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.code_catalogs.enums import CatalogType
from app.modules.code_catalogs.models import CodeCatalog

# ---------------------------------------------------------------------------
# Module logger — safe to log seed operations (NOT PHI)
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


async def seed_code_catalogs(db: AsyncSession) -> None:
    """
    Seed the code_catalogs table with common clinical reference codes.

    This function is idempotent — it uses ON CONFLICT DO NOTHING so
    running it multiple times is safe and produces no duplicates.

    Args:
        db: Async database session. Caller is responsible for commit.
    """
    all_codes = (
        _get_icd10_codes()
        + _get_atc_codes()
        + _get_loinc_codes()
        + _get_snomed_codes()
    )

    # Use PostgreSQL INSERT ... ON CONFLICT DO NOTHING for idempotency
    stmt = insert(CodeCatalog).values(all_codes)
    stmt = stmt.on_conflict_do_nothing(
        constraint="uq_code_catalog_type_code"
    )

    await db.execute(stmt)
    await db.flush()

    logger.info(
        "code_catalogs_seeded",
        total_codes=len(all_codes),
        icd10_count=len(_get_icd10_codes()),
        atc_count=len(_get_atc_codes()),
        loinc_count=len(_get_loinc_codes()),
        snomed_count=len(_get_snomed_codes()),
    )


def _get_icd10_codes() -> list[dict]:
    """
    Return common ICD-10 disease codes for seeding.

    Covers the most prevalent conditions in sub-Saharan Africa:
    diabetes, hypertension, cardiovascular disease, respiratory disease,
    kidney disease, infectious diseases, and common acute conditions.

    Returns:
        List of dicts ready for bulk insert into code_catalogs table.
    """
    return [
        # --- Diabetes (E10-E14) ---
        _icd10("E10.9", "Type 1 diabetes mellitus, without complications",
               fr="Diabète sucré de type 1, sans complication",
               pt="Diabetes mellitus tipo 1, sem complicações"),
        _icd10("E11.9", "Type 2 diabetes mellitus, without complications",
               fr="Diabète sucré de type 2, sans complication",
               pt="Diabetes mellitus tipo 2, sem complicações",
               parent="E11"),
        _icd10("E11.65", "Type 2 diabetes mellitus with hyperglycemia"),
        _icd10("E11.22", "Type 2 diabetes mellitus with diabetic chronic kidney disease"),
        _icd10("E11.40", "Type 2 diabetes mellitus with diabetic neuropathy"),
        _icd10("E11.51", "Type 2 diabetes mellitus with diabetic peripheral angiopathy"),
        # --- Hypertension (I10-I16) ---
        _icd10("I10", "Essential (primary) hypertension",
               fr="Hypertension artérielle essentielle (primitive)",
               pt="Hipertensão essencial (primária)"),
        _icd10("I11.9", "Hypertensive heart disease without heart failure"),
        _icd10("I12.9", "Hypertensive chronic kidney disease, stage 1-4"),
        _icd10("I13.10", "Hypertensive heart and CKD without heart failure"),
        # --- Cerebrovascular Disease (I60-I69) ---
        _icd10("I63.9", "Cerebral infarction, unspecified",
               fr="Infarctus cérébral, sans précision",
               pt="Infarto cerebral, não especificado"),
        _icd10("I64", "Stroke, not specified as hemorrhage or infarction",
               fr="Accident vasculaire cérébral, non précisé",
               pt="Acidente vascular cerebral, não especificado"),
        _icd10("I61.9", "Nontraumatic intracerebral hemorrhage, unspecified"),
        # --- Ischemic Heart Disease (I20-I25) ---
        _icd10("I21.9", "Acute myocardial infarction, unspecified",
               fr="Infarctus aigu du myocarde, sans précision",
               pt="Infarto agudo do miocárdio, não especificado"),
        _icd10("I25.10", "Atherosclerotic heart disease of native coronary artery"),
        _icd10("I20.9", "Angina pectoris, unspecified"),
        # --- Heart Failure (I50) ---
        _icd10("I50.9", "Heart failure, unspecified",
               fr="Insuffisance cardiaque, sans précision",
               pt="Insuficiência cardíaca, não especificada"),
        _icd10("I50.22", "Chronic systolic (congestive) heart failure"),
        # --- Chronic Kidney Disease (N18) ---
        _icd10("N18.3", "Chronic kidney disease, stage 3",
               fr="Maladie rénale chronique, stade 3",
               pt="Doença renal crônica, estágio 3"),
        _icd10("N18.4", "Chronic kidney disease, stage 4"),
        _icd10("N18.5", "Chronic kidney disease, stage 5"),
        _icd10("N18.6", "End stage renal disease"),
        # --- COPD and Respiratory (J40-J47) ---
        _icd10("J44.1", "COPD with acute exacerbation",
               fr="BPCO avec exacerbation aiguë",
               pt="DPOC com exacerbação aguda"),
        _icd10("J44.0", "COPD with acute lower respiratory infection"),
        _icd10("J45.20", "Mild intermittent asthma, uncomplicated"),
        _icd10("J45.40", "Moderate persistent asthma, uncomplicated"),
        _icd10("J18.9", "Pneumonia, unspecified organism",
               fr="Pneumonie, sans précision",
               pt="Pneumonia, organismo não especificado"),
        # --- HIV/AIDS (B20) ---
        _icd10("B20", "HIV disease",
               fr="Maladie à VIH",
               pt="Doença pelo HIV"),
        # --- Tuberculosis (A15-A19) ---
        _icd10("A15.0", "Tuberculosis of lung",
               fr="Tuberculose pulmonaire",
               pt="Tuberculose pulmonar"),
        # --- Malaria (B50-B54) ---
        _icd10("B50.9", "Plasmodium falciparum malaria, unspecified",
               fr="Paludisme à Plasmodium falciparum, sans précision",
               pt="Malária por Plasmodium falciparum, não especificada"),
        _icd10("B51.9", "Plasmodium vivax malaria, unspecified"),
        # --- Anemia (D50-D64) ---
        _icd10("D50.9", "Iron deficiency anemia, unspecified",
               fr="Anémie ferriprive, sans précision",
               pt="Anemia por deficiência de ferro, não especificada"),
        _icd10("D57.1", "Sickle-cell disease without crisis"),
        # --- Liver Disease ---
        _icd10("K74.60", "Unspecified cirrhosis of liver"),
        _icd10("B18.1", "Chronic viral hepatitis B without delta-agent"),
        # --- Obesity and Metabolic ---
        _icd10("E66.9", "Obesity, unspecified",
               fr="Obésité, sans précision",
               pt="Obesidade, não especificada"),
        _icd10("E78.5", "Hyperlipidemia, unspecified"),
        _icd10("E78.0", "Pure hypercholesterolemia"),
        # --- Thyroid ---
        _icd10("E03.9", "Hypothyroidism, unspecified"),
        _icd10("E05.90", "Thyrotoxicosis, unspecified"),
        # --- Mental Health ---
        _icd10("F32.1", "Major depressive disorder, single episode, moderate",
               fr="Épisode dépressif moyen",
               pt="Episódio depressivo moderado"),
        _icd10("F41.1", "Generalized anxiety disorder"),
        # --- Musculoskeletal ---
        _icd10("M54.5", "Low back pain"),
        _icd10("M17.9", "Osteoarthritis of knee, unspecified"),
        # --- Acute Conditions ---
        _icd10("J06.9", "Acute upper respiratory infection, unspecified"),
        _icd10("A09", "Infectious gastroenteritis and colitis, unspecified",
               fr="Gastro-entérite infectieuse, sans précision",
               pt="Gastroenterite infecciosa, não especificada"),
        _icd10("N39.0", "Urinary tract infection, site not specified"),
        _icd10("R50.9", "Fever, unspecified"),
        # --- Pregnancy-related ---
        _icd10("O24.41", "Gestational diabetes mellitus in pregnancy"),
        _icd10("O13.9", "Gestational hypertension without proteinuria"),
        # --- Cancer (common) ---
        _icd10("C50.919", "Malignant neoplasm of unspecified site of breast"),
        _icd10("C34.90", "Malignant neoplasm of unspecified part of bronchus or lung"),
    ]


def _get_atc_codes() -> list[dict]:
    """
    Return common ATC drug classification codes for seeding.

    Covers the most commonly prescribed medications in sub-Saharan Africa:
    antidiabetics, antihypertensives, statins, antibiotics, antimalarials,
    analgesics, and antiretrovirals.

    Returns:
        List of dicts ready for bulk insert into code_catalogs table.
    """
    return [
        # --- Antidiabetics (A10) ---
        _atc("A10BA02", "Metformin",
             fr="Metformine", pt="Metformina"),
        _atc("A10BB01", "Glibenclamide",
             fr="Glibenclamide", pt="Glibenclamida"),
        _atc("A10BH01", "Sitagliptin"),
        _atc("A10BK01", "Dapagliflozin"),
        _atc("A10AE04", "Insulin glargine",
             fr="Insuline glargine", pt="Insulina glargina"),
        # --- Antihypertensives (C02, C03, C07, C08, C09) ---
        _atc("C08CA01", "Amlodipine",
             fr="Amlodipine", pt="Anlodipino"),
        _atc("C09AA02", "Enalapril",
             fr="Énalapril", pt="Enalapril"),
        _atc("C09CA01", "Losartan",
             fr="Losartan", pt="Losartana"),
        _atc("C03CA01", "Furosemide",
             fr="Furosémide", pt="Furosemida"),
        _atc("C03AA03", "Hydrochlorothiazide"),
        _atc("C07AB02", "Metoprolol"),
        _atc("C07AB07", "Bisoprolol"),
        # --- Statins and Lipid-Lowering (C10) ---
        _atc("C10AA05", "Atorvastatin",
             fr="Atorvastatine", pt="Atorvastatina"),
        _atc("C10AA01", "Simvastatin"),
        _atc("C10AA07", "Rosuvastatin"),
        # --- Antiplatelet and Anticoagulant (B01) ---
        _atc("B01AC06", "Acetylsalicylic acid (Aspirin)",
             fr="Acide acétylsalicylique (Aspirine)",
             pt="Ácido acetilsalicílico (Aspirina)"),
        _atc("B01AF01", "Rivaroxaban"),
        _atc("B01AC04", "Clopidogrel"),
        # --- Analgesics (N02) ---
        _atc("N02BE01", "Paracetamol (Acetaminophen)",
             fr="Paracétamol", pt="Paracetamol"),
        _atc("N02BA01", "Acetylsalicylic acid"),
        _atc("M01AE01", "Ibuprofen",
             fr="Ibuprofène", pt="Ibuprofeno"),
        # --- Antibiotics (J01) ---
        _atc("J01CA04", "Amoxicillin",
             fr="Amoxicilline", pt="Amoxicilina"),
        _atc("J01FA10", "Azithromycin",
             fr="Azithromycine", pt="Azitromicina"),
        _atc("J01MA02", "Ciprofloxacin"),
        _atc("J01DD04", "Ceftriaxone"),
        # --- Antimalarials (P01B) ---
        _atc("P01BF01", "Artemether/Lumefantrine",
             fr="Artéméther/Luméfantrine",
             pt="Arteméter/Lumefantrina"),
        # --- Antiretrovirals (J05) ---
        _atc("J05AF13", "Tenofovir alafenamide"),
        _atc("J05AR13", "Tenofovir/Emtricitabine/Dolutegravir"),
        # --- Proton Pump Inhibitors (A02BC) ---
        _atc("A02BC01", "Omeprazole",
             fr="Oméprazole", pt="Omeprazol"),
        # --- Corticosteroids (H02) ---
        _atc("H02AB06", "Prednisolone",
             fr="Prednisolone", pt="Prednisolona"),
    ]


def _get_loinc_codes() -> list[dict]:
    """
    Return common LOINC laboratory test codes for seeding.

    Covers the most frequently ordered lab tests in primary care and
    chronic disease management: metabolic panel, lipid panel, CBC,
    diabetes monitoring, renal function, liver function, and infectious
    disease markers.

    Returns:
        List of dicts ready for bulk insert into code_catalogs table.
    """
    return [
        # --- Glucose and Diabetes Monitoring ---
        _loinc("2345-7", "Glucose [Mass/volume] in Serum or Plasma",
               fr="Glucose sérique", pt="Glicose sérica"),
        _loinc("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood",
               fr="Hémoglobine glyquée (HbA1c)",
               pt="Hemoglobina glicada (HbA1c)"),
        _loinc("14749-6", "Glucose [Mass/volume] in Serum or Plasma --fasting"),
        _loinc("1558-6", "Fasting glucose [Mass/volume] in Serum or Plasma"),
        # --- Renal Function ---
        _loinc("2160-0", "Creatinine [Mass/volume] in Serum or Plasma",
               fr="Créatinine sérique", pt="Creatinina sérica"),
        _loinc("3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma"),
        _loinc("33914-3", "Glomerular filtration rate/1.73 sq M (eGFR)",
               fr="Débit de filtration glomérulaire estimé (DFGe)",
               pt="Taxa de filtração glomerular estimada (TFGe)"),
        _loinc("2823-3", "Potassium [Moles/volume] in Serum or Plasma"),
        _loinc("2951-2", "Sodium [Moles/volume] in Serum or Plasma"),
        # --- Lipid Panel ---
        _loinc("2093-3", "Cholesterol [Mass/volume] in Serum or Plasma",
               fr="Cholestérol total", pt="Colesterol total"),
        _loinc("2085-9", "HDL Cholesterol [Mass/volume] in Serum or Plasma"),
        _loinc("13457-7", "LDL Cholesterol [Mass/volume] in Serum or Plasma (calculated)"),
        _loinc("2571-8", "Triglyceride [Mass/volume] in Serum or Plasma",
               fr="Triglycérides", pt="Triglicerídeos"),
        # --- Complete Blood Count ---
        _loinc("718-7", "Hemoglobin [Mass/volume] in Blood",
               fr="Hémoglobine sanguine", pt="Hemoglobina sanguínea"),
        _loinc("6690-2", "Leukocytes [#/volume] in Blood (WBC)"),
        _loinc("777-3", "Platelets [#/volume] in Blood"),
        _loinc("789-8", "Erythrocytes [#/volume] in Blood (RBC)"),
        _loinc("4544-3", "Hematocrit [Volume Fraction] of Blood"),
        # --- Liver Function ---
        _loinc("1742-6", "Alanine aminotransferase [U/volume] in Serum (ALT)",
               fr="ALAT (TGP)", pt="ALT (TGP)"),
        _loinc("1920-8", "Aspartate aminotransferase [U/volume] in Serum (AST)"),
        _loinc("1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma"),
        _loinc("6768-6", "Alkaline phosphatase [U/volume] in Serum or Plasma"),
        # --- Infectious Disease ---
        _loinc("20447-9", "HIV 1+2 Ab [Presence] in Serum",
               fr="Anticorps VIH 1+2", pt="Anticorpos HIV 1+2"),
        _loinc("5196-1", "Hepatitis B surface Ag [Presence] in Serum"),
        _loinc("32167-9", "Malaria parasites [Presence] in Blood by Light microscopy",
               fr="Parasites du paludisme (goutte épaisse)",
               pt="Parasitas da malária (gota espessa)"),
        # --- Thyroid ---
        _loinc("3016-3", "Thyrotropin [Units/volume] in Serum or Plasma (TSH)"),
        _loinc("3026-2", "Thyroxine (T4) free [Mass/volume] in Serum or Plasma"),
        # --- Urinalysis ---
        _loinc("5811-5", "Specific gravity of Urine by Test strip"),
        _loinc("2514-8", "Protein [Mass/volume] in Urine"),
        # --- Coagulation ---
        _loinc("5902-2", "Prothrombin time (PT)"),
        _loinc("6301-6", "INR in Platelet poor plasma by Coagulation assay"),
    ]


def _get_snomed_codes() -> list[dict]:
    """
    Return common SNOMED CT procedure codes for seeding.

    Covers frequently performed clinical procedures in hospital settings:
    surgical procedures, diagnostic procedures, and therapeutic procedures.

    Returns:
        List of dicts ready for bulk insert into code_catalogs table.
    """
    return [
        # --- Surgical Procedures ---
        _snomed("80146002", "Appendectomy",
                fr="Appendicectomie", pt="Apendicectomia"),
        _snomed("174041007", "Cesarean section",
                fr="Césarienne", pt="Cesariana"),
        _snomed("397956004", "Cholecystectomy",
                fr="Cholécystectomie", pt="Colecistectomia"),
        _snomed("44558001", "Hernia repair"),
        _snomed("265764009", "Renal dialysis",
                fr="Dialyse rénale", pt="Diálise renal"),
        _snomed("18286008", "Catheterization of urinary bladder"),
        _snomed("387713003", "Surgical wound repair"),
        # --- Diagnostic Procedures ---
        _snomed("86273004", "Biopsy",
                fr="Biopsie", pt="Biópsia"),
        _snomed("71388002", "Diagnostic procedure (general)"),
        _snomed("77477000", "Computed tomography (CT scan)",
                fr="Tomodensitométrie (scanner)",
                pt="Tomografia computadorizada"),
        _snomed("113091000", "Magnetic resonance imaging (MRI)"),
        _snomed("16310003", "Ultrasonography",
                fr="Échographie", pt="Ultrassonografia"),
        _snomed("104001", "Excision of lesion"),
        # --- Therapeutic Procedures ---
        _snomed("33195004", "Blood transfusion",
                fr="Transfusion sanguine", pt="Transfusão de sangue"),
        _snomed("182813001", "Emergency treatment"),
        _snomed("225358003", "Wound care"),
        _snomed("386637004", "Obstetric procedure"),
        _snomed("274025005", "Bone fracture reduction"),
        _snomed("40701008", "Echocardiography"),
        _snomed("252416005", "Electrocardiogram (ECG)",
                fr="Électrocardiogramme (ECG)",
                pt="Eletrocardiograma (ECG)"),
    ]


# ---------------------------------------------------------------------------
# Helper functions for building seed data dicts
# ---------------------------------------------------------------------------

def _icd10(
    code: str,
    name_en: str,
    fr: str | None = None,
    pt: str | None = None,
    parent: str | None = None,
) -> dict:
    """Build a seed dict for an ICD-10 code entry."""
    return {
        "catalog_type": CatalogType.ICD10.value,
        "code": code,
        "display_name_en": name_en,
        "display_name_fr": fr,
        "display_name_pt": pt,
        "is_active": True,
        "parent_code": parent,
    }


def _atc(
    code: str,
    name_en: str,
    fr: str | None = None,
    pt: str | None = None,
    parent: str | None = None,
) -> dict:
    """Build a seed dict for an ATC drug code entry."""
    return {
        "catalog_type": CatalogType.ATC.value,
        "code": code,
        "display_name_en": name_en,
        "display_name_fr": fr,
        "display_name_pt": pt,
        "is_active": True,
        "parent_code": parent,
    }


def _loinc(
    code: str,
    name_en: str,
    fr: str | None = None,
    pt: str | None = None,
    parent: str | None = None,
) -> dict:
    """Build a seed dict for a LOINC lab test code entry."""
    return {
        "catalog_type": CatalogType.LOINC.value,
        "code": code,
        "display_name_en": name_en,
        "display_name_fr": fr,
        "display_name_pt": pt,
        "is_active": True,
        "parent_code": parent,
    }


def _snomed(
    code: str,
    name_en: str,
    fr: str | None = None,
    pt: str | None = None,
    parent: str | None = None,
) -> dict:
    """Build a seed dict for a SNOMED CT procedure code entry."""
    return {
        "catalog_type": CatalogType.SNOMED.value,
        "code": code,
        "display_name_en": name_en,
        "display_name_fr": fr,
        "display_name_pt": pt,
        "is_active": True,
        "parent_code": parent,
    }
