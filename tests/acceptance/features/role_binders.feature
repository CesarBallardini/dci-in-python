@bdd
Feature: Four ways to lend a role, and what each one costs
  As someone choosing between the four binders in banking/dci/
  I want APPROACHES.md's comparison table to be executable
  So that "measured, not argued" is true of every cell in it

  The four binders share everything except one method, `_bind`. Four rather
  than one because the trade between them is the whole subject. Each example
  row below is one cell of the table in "Four ways to lend a role", and there
  is deliberately no row where every answer is the one you want.

  Background:
    Given an account "Alice" with 1000 ARS
    And an account "Bob" with 0 ARS

  Scenario Outline: What the type and the error messages call the object
    When a transfer is opened with the <binder> binder
    Then the type of "Alice" reports itself as "<name>"
    And asking "Alice" for an undefined attribute blames "<name>"

    Examples: the synthesized class keeps its own name
      | binder     | name                  |
      | class      | Account@SourceAccount |
      | serialized | Account@SourceAccount |

    Examples: or wears the data class's name, which is the point of the other two
      | binder      | name    |
      | transparent | Account |
      | instance    | Account |

  Scenario Outline: Pickling a participant while the transfer is in flight
    When a transfer is opened with the <binder> binder
    And "Alice" is pickled
    Then it <outcome>

    Examples: the three class binders refuse on the spot, which is the good case
      | binder      | outcome                     |
      | class       | is refused as it is written |
      | transparent | is refused as it is written |
      | serialized  | is refused as it is written |

    Examples: instance binding writes bytes that nobody can read back
      | binder   | outcome                          |
      | instance | is written and fails on the read |

  Scenario Outline: Two transfers out of one account, opened by one thread
    Given a shared account with 1000000 ARS
    When a transfer out of it is opened with the <binder> binder
    And a second transfer out of it is opened with the same binder
    Then the second one <result>

    Examples: all four refuse, including the locking one -- its lock is re-entrant to its owner
      | binder      | result                            |
      | class       | is refused with an MRO error      |
      | transparent | is refused with an MRO error      |
      | serialized  | is refused with an MRO error      |
      | instance    | is refused as the name is taken   |

  @threads
  Scenario Outline: Two transfers out of one account, served by two threads
    Given a shared account with 1000000 ARS
    When two threads run overlapping transfers out of it with the <binder> binder
    Then <result>

    Examples: the class is state of the object, and the object is shared
      | binder      | result                                        |
      | class       | the thread that arrived second fails          |
      | transparent | the thread that arrived second fails          |

    Examples: holding the participants is the only thing that actually works
      | binder     | result                  |
      | serialized | both transfers complete |

    Examples: instance binding refuses the second rather than writing over the first
      | binder   | result                                    |
      | instance | the thread that arrived second is refused |

  @threads
  Scenario Outline: One account paying a transfer out while another pays into it
    Given a shared account with 1000000 ARS
    When two threads run a transfer out of it and a transfer into it with the <binder> binder
    Then <result>

    Examples: the two roles stack, so nothing refuses -- and the last one out puts the first one's role back
      | binder      | result                                      |
      | class       | the account is left playing a role for good |
      | transparent | the account is left playing a role for good |

    Examples: holding the participants keeps the two transfers from overlapping at all
      | binder     | result                      |
      | serialized | the account is itself again |

    Examples: instance binding takes back only the names it wrote, so the order it leaves in does not matter
      | binder   | result                      |
      | instance | the account is itself again |

  Scenario Outline: A role that wants to contribute a special method
    When a role defining __lt__ is lent to an amount with the <binder> binder
    Then the less-than operator on the amount <outcome>

    Examples: special methods are resolved on the type
      | binder | outcome                |
      | class  | runs the role's method |

    Examples: so instance binding declines to lend one it knows could never run
      | binder   | outcome          |
      | instance | ignores the role |

  Scenario Outline: A context is a use case in flight, not a nesting construct
    When a transfer is opened with the <binder> binder
    And the same context is entered a second time
    Then it is refused as not re-entrant

    Examples:
      | binder      |
      | class       |
      | transparent |
      | serialized  |
      | instance    |

  Scenario Outline: A binding that fails part way leaves nothing behind
    Given a source that cannot play a role
    When a transfer out of it is attempted with the <binder> binder
    Then the transfer is refused
    And no participant is left holding a role
    And no context is left running

    Examples:
      | binder      |
      | class       |
      | transparent |
      | serialized  |
      | instance    |
