// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title AgentRegistry
/// @notice ERC-8004 identity registry for AI agents on-chain.
/// @dev Agents register with metadata, owners verify them, and a reputation score (0–100)
///      tracks trustworthiness. All operations are gas-optimized with single-slot reads.
contract AgentRegistry {

    // ──────────────────────────── Structs ────────────────────────────

    struct AgentInfo {
        string name;
        string metadataURI;
        address owner;
        uint48 registeredAt;
        bool verified;
        uint8 reputation;
    }

    // ──────────────────────────── State ────────────────────────────

    uint256 public nextAgentId;
    uint256 public totalRegistered;

    /// @dev agentId => AgentInfo
    mapping(uint256 => AgentInfo) internal _agents;

    /// @dev name => agentId (for uniqueness)
    mapping(bytes32 => uint256) public nameToAgentId;

    /// @dev owner => agentId[] (for bulk queries)
    mapping(address => uint256[]) public ownerAgents;

    // ──────────────────────────── Errors ────────────────────────────

    error NameTaken();
    error NameEmpty();
    error URIEmpty();
    error AgentNotFound(uint256 agentId);
    error NotOwner(address caller, address owner);
    error AlreadyRegistered();
    error InvalidReputation(uint8 score);

    // ──────────────────────────── Events ────────────────────────────

    event AgentRegistered(uint256 indexed agentId, string name, address indexed owner);
    event AgentVerified(uint256 indexed agentId);
    event ReputationUpdated(uint256 indexed agentId, uint8 oldScore, uint8 newScore);

    // ──────────────────────────── Modifiers ────────────────────────────

    modifier onlyAgentOwner(uint256 agentId) {
        if (_agents[agentId].owner == address(0)) revert AgentNotFound(agentId);
        if (msg.sender != _agents[agentId].owner) revert NotOwner(msg.sender, _agents[agentId].owner);
        _;
    }

    // ──────────────────────────── Core Functions ────────────────────────────

    /// @notice Register a new AI agent.
    /// @dev Name must be unique and non-empty. Caller becomes the owner.
    ///      reputation starts at 0, verified starts false.
    /// @param name_ Human-readable agent name (must be unique).
    /// @param metadataURI_ IPFS/HTTP URI to off-chain metadata (JSON, image, etc.).
    /// @return agentId The unique identifier of the registered agent.
    function registerAgent(
        string calldata name_,
        string calldata metadataURI_
    ) external returns (uint256 agentId) {
        if (bytes(name_).length == 0) revert NameEmpty();
        if (bytes(metadataURI_).length == 0) revert URIEmpty();

        bytes32 nameHash = keccak256(abi.encodePacked(name_));
        if (nameToAgentId[nameHash] != 0) revert NameTaken();

        agentId = nextAgentId++;

        AgentInfo storage a = _agents[agentId];
        a.name = name_;
        a.metadataURI = metadataURI_;
        a.owner = msg.sender;
        a.registeredAt = uint48(block.timestamp);
        a.verified = false;
        a.reputation = 0;

        nameToAgentId[nameHash] = agentId;
        ownerAgents[msg.sender].push(agentId);
        totalRegistered++;

        emit AgentRegistered(agentId, name_, msg.sender);
    }

    /// @notice Mark an agent as verified. Only the agent's owner can verify.
    /// @param agentId Agent to verify.
    function verifyAgent(uint256 agentId)
        external
        onlyAgentOwner(agentId)
    {
        AgentInfo storage a = _agents[agentId];
        if (!a.verified) {
            a.verified = true;
            emit AgentVerified(agentId);
        }
    }

    /// @notice Update an agent's reputation score (0–100).
    /// @dev Only the agent's owner can update reputation.
    /// @param agentId Agent to update.
    /// @param newScore New reputation value (0–100).
    function updateReputation(uint256 agentId, uint8 newScore)
        external
        onlyAgentOwner(agentId)
    {
        if (newScore > 100) revert InvalidReputation(newScore);

        AgentInfo storage a = _agents[agentId];
        uint8 oldScore = a.reputation;
        a.reputation = newScore;
        emit ReputationUpdated(agentId, oldScore, newScore);
    }

    // ──────────────────────────── Views ────────────────────────────

    /// @notice Get full agent information.
    /// @param agentId Agent to query.
    /// @return name Agent name.
    /// @return metadataURI Metadata URI.
    /// @return owner Owner address.
    /// @return registeredAt Registration timestamp.
    /// @return verified Verification status.
    /// @return reputation Reputation score (0–100).
    function getAgent(uint256 agentId) external view returns (
        string memory name,
        string memory metadataURI,
        address owner,
        uint48 registeredAt,
        bool verified,
        uint8 reputation
    ) {
        AgentInfo storage a = _agents[agentId];
        if (a.owner == address(0)) revert AgentNotFound(agentId);
        return (a.name, a.metadataURI, a.owner, a.registeredAt, a.verified, a.reputation);
    }

    /// @notice Check if an agent is registered and active.
    /// @param agentId Agent to check.
    /// @return True if registered (owner != address(0)).
    function isRegistered(uint256 agentId) external view returns (bool) {
        return _agents[agentId].owner != address(0);
    }

    /// @notice Get all agent IDs owned by an address.
    /// @param owner Owner address to query.
    /// @return Array of agent IDs.
    function getAgentsByOwner(address owner) external view returns (uint256[] memory) {
        return ownerAgents[owner];
    }

    /// @notice Resolve a name to its agent ID.
    /// @param name_ The agent name to look up.
    /// @return agentId The agent ID (0 if not found).
    function resolveName(string calldata name_) external view returns (uint256 agentId) {
        return nameToAgentId[keccak256(abi.encodePacked(name_))];
    }
}
