from openai_function_call import OpenAISchema
from pydantic import Field
from typing import List, Any

# Example page: https://www.cftc.gov/PressRoom/PressReleases/8726-23
class CFTCEnforcementDetails(OpenAISchema):
    """Extract information regarding CFTC enforcement action(s)"""
    date:               str = Field(..., description="Date of the action")
    regulator:          str = Field(..., description="Name of the regulator bringing the action")
    enforcement_type:   str = Field(..., description="Type of enforcement action: warning letter, civil fines, suspension/revocation of license, civil lawsuit, criminal lawsuit")
    impacted_entities:  List[str] = Field(..., description="Names of entities impacted by the enforcement action")
    related_case:       str = Field(..., description="Case number(s) of related actions")
    defendants:         List[str] = Field(..., description="Names of individuals or entities named as defendants")
    alleged_crimes:     List[str] = Field(..., description="Specific crimes alleged")
    penalty_amount:     int = Field( ..., description="Penalty amount, if any")


# Example page: https://www.lapdonline.org/newsroom/officer-involved-shooting-in-hollywood-area-nrf059-18ma/
class LAPDEventDetails(OpenAISchema):
    """Details of LAPD press releases"""
    date:       str = Field(..., description="Date of event")
    injured:    str = Field(..., description="Who was injured in the event, if any")
    serial:     int = Field(..., description="Officer badge or serial number, if applicable")
    deceased:   str = Field(..., description="Names of those who are deceased, if any")

# Add in additional schemas below: