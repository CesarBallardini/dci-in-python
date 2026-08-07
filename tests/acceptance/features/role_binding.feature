@bdd
Feature: Which domain objects can play a role
  As someone deciding whether DCI fits a system that already exists
  I want APPROACHES.md's table of domain-object styles to be executable
  So that no answer in it can go stale without the suite saying so

  The question that decides whether DCI is usable at all is not about the
  mechanism, it is about the objects: you did not write the account, it came
  out of a database or out of a model. Every row below is one cell of the
  table in "Whether a persisted object can play a role".

  Scenario Outline: Lending the role by reassigning the object's class
    Given a source and a destination written as <style>
    When they run a transfer of 250 with the role bound on the class
    Then the transfer <outcome>

    Examples: the domain class stayed plain Python
      | style            | outcome  |
      | a plain class    | succeeds |
      | a pydantic model | succeeds |

    Examples: a framework decided the class layout instead
      | style              | outcome    |
      | a frozen dataclass | is refused |
      | an attrs class     | is refused |

  Scenario Outline: Lending the role by writing it into the instance
    Given a source and a destination written as <style>
    When they run a transfer of 250 with the role bound on the instance
    Then the transfer <outcome>

    Examples: instance binding never touches the class, so the layout is irrelevant
      | style              | outcome  |
      | a plain class      | succeeds |
      | a pydantic model   | succeeds |
      | a frozen dataclass | succeeds |

    Examples: unless there is no instance dictionary to write into
      | style          | outcome    |
      | an attrs class | is refused |

  @integration
  Scenario Outline: An entity loaded from a real database
    Given a source and a destination mapped <mapping> and loaded from the database
    When they run a transfer of 250 with the role bound on the <binding>
    Then the transfer <outcome>

    Examples: with class binding the mapping style decides it
      | mapping       | binding | outcome    |
      | imperatively  | class   | succeeds   |
      | declaratively | class   | is refused |

    Examples: instance binding takes the entity everyone actually writes
      | mapping       | binding  | outcome  |
      | imperatively  | instance | succeeds |
      | declaratively | instance | succeeds |

  @integration
  Scenario: The change made through the role reaches the database
    Given a source and a destination mapped imperatively and loaded from the database
    When they run a transfer of 250 with the role bound on the class
    Then the transfer succeeds
    And reloading them in a new session shows 750 and 250
